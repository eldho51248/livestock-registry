import logging
import re
from datetime import date

from openg2p_registry_core.services import G2PRegisterDomainService

from .audit_snapshot import AuditSnapshotMixin

from .domain_validation_utils import (
    as_float,
    as_int,
    ear_tag_used_by_other_animal,
    get_species_config,
    is_blank,
    parse_date,
    secondary_identifier_used_by_other_animal,
    validation_error,
)

_logger = logging.getLogger("g2p-register-domain-service")


# ET followed by exactly 10 digits, as enforced by _check_ear_tag_format in
# g2p_livestock_registry/models/live_stock_registry_line.py.
_EAR_TAG_PATTERN = re.compile(r"^ET\d{10}$")

# Whether a species requires an ear tag, and whether it's recorded as a
# flock/group rather than one row per individual, is NOT a hardcoded species
# list here anymore — it's per-value config on the LIVESTOCK_SPECIES
# attribute (Configuration > Attributes > Species > Edit > "Requires Ear
# Tag" / "Flock / Group Species"), read live via get_species_config
# (domain_validation_utils.py, backed by G2PAttributeValueSpeciesConfig).
# That keeps adding a new tagless/flock species (e.g. Duck, Rabbit) a
# Configuration change, not a code change.

# field -> human label used in the "Please provide the ... " message, mirroring
# the fields marked "widget-required" on the Livestock Details form.
# ear_tag_id/secondary_identifier are intentionally not listed here — which of
# the two is required depends on species, so that's handled separately by
# _validate_identifier_required. date_of_birth is likewise not listed here —
# see _validate_date_of_birth_required.
_REQUIRED_FIELDS = {
    "species": "species",
    "breed": "breed",
    # Stays required for every species, no exception for a flock species —
    # unlike date_of_birth below, there's no per-field carve-out here: this
    # is G2R-135's mandatory constraint. GenderEnum.MIXED (models/enums.py)
    # is what lets a flock row satisfy it honestly instead of picking an
    # arbitrary MALE/FEMALE for 500 birds of both sexes.
    "gender": "gender",
    "vaccination_status": "vaccination status",
    "health_status": "health status",
    "registration_date": "registration date",
}


class G2PRegisterDomainServiceAnimal(AuditSnapshotMixin, G2PRegisterDomainService):

    async def validate_domain_attributes(self, records: list[dict]):
        for record in records:
            self._validate_required_fields(record)
            requires_ear_tag, is_flock_species = await get_species_config(record.get("species"))
            self._validate_identifier_required(record, requires_ear_tag)
            self._validate_ear_tag_id(record)
            self._validate_quantity(record, is_flock_species)
            self._validate_date_of_birth_required(record, is_flock_species)
            self._validate_not_in_future(record, "date_of_birth")
            self._validate_not_in_future(record, "registration_date")
            self._validate_weight(record)
            self._populate_age_from_date_of_birth(record)
        # Runs only once every record above has passed — so by this point
        # every ear_tag_id/species/breed used below is known non-blank and
        # already in the normalized ET+10-digit form (when present), and
        # every secondary_identifier used below is known non-blank for the
        # tag-exempt species that require it.
        await self._validate_no_duplicate_ear_tags(records)
        await self._validate_no_duplicate_secondary_identifiers(records)

    def _validate_required_fields(self, record: dict) -> None:
        for field, label in _REQUIRED_FIELDS.items():
            if is_blank(record.get(field)):
                validation_error(f"Please provide the {label} before saving the record.")

    def _validate_identifier_required(self, record: dict, requires_ear_tag: bool) -> None:
        """Every animal needs an identifier, but which one is mandatory
        depends on species: `ear_tag_id` when the species' "Requires Ear
        Tag" config says so, `secondary_identifier` (leg band, wing tag,
        hive number, RFID, ...) otherwise, for a species that has no ear to
        tag. `requires_ear_tag` comes from get_species_config, called once
        per record by the caller — see validate_domain_attributes. Enforced
        here too, not just via the form's "require" rules — see
        require_field's docstring on why the backend can't rely on the
        frontend alone for a required-field check.
        """
        if requires_ear_tag:
            if is_blank(record.get("ear_tag_id")):
                validation_error("Please provide the livestock ear tag before saving the record.")
        elif is_blank(record.get("secondary_identifier")):
            validation_error(
                "Please provide a secondary identifier (leg band, wing tag, "
                "hive number, etc.) before saving the record — this species "
                "has no ear to attach an ear tag to."
            )

    def _validate_quantity(self, record: dict, is_flock_species: bool) -> None:
        """A flock-species row stands for the whole group, so it needs a
        headcount — reject it the same way a missing identifier is
        rejected above. Not required, and not otherwise validated, for an
        individually-tracked species: one row already *is* one animal there,
        so a quantity field on it has no meaning to enforce.
        """
        if not is_flock_species:
            return
        quantity = as_int(record.get("quantity"))
        if quantity is None:
            validation_error(
                "Please provide the quantity (head count) before saving the record — "
                "this species is recorded as a flock, not one row per animal."
            )
        elif quantity <= 0:
            validation_error("quantity must be greater than zero")
        else:
            # Store the parsed int, not whatever string/float the form sent —
            # same normalize-on-write approach as _validate_ear_tag_id above.
            record["quantity"] = quantity

    def _validate_date_of_birth_required(self, record: dict, is_flock_species: bool) -> None:
        """Required for an individually-tracked animal, same as before. Not
        required for a flock-species row: a flock of 500 birds hatched (or
        acquired) at different times has no single date_of_birth that's true
        for the group, so forcing one here would just mean picking an
        arbitrary date. Unlike gender, there's no named mandatory-constraint
        for this field, so it's fine to drop the requirement outright rather
        than needing a "Mixed/Not Applicable" escape hatch.
        """
        if is_flock_species:
            return
        if is_blank(record.get("date_of_birth")):
            validation_error("Please provide the date of birth before saving the record.")

    def _validate_ear_tag_id(self, record: dict) -> None:
        value = record.get("ear_tag_id")
        if value is None or str(value).strip() == "":
            return
        normalized = re.sub(r"\s+", "", str(value)).upper()
        if not _EAR_TAG_PATTERN.match(normalized):
            validation_error(
                "ear_tag_id must be ET followed by exactly 10 digits, e.g. ET0000000013"
            )
        # Store the normalized form, not whatever casing/spacing was typed —
        # otherwise "et5678765435" and "ET5678765435" would both pass this
        # check yet be treated as different tags by the duplicate check
        # below (and by ear_tag_exists/get_animal_species elsewhere).
        record["ear_tag_id"] = normalized

    async def _validate_no_duplicate_ear_tags(self, records: list[dict]) -> None:
        """Two different animals must never share an ear tag with the same
        species and breed — mirroring the Old System's duplicate check,
        which this section had no equivalent of at all. Two layers:

        1. Within this same save (this farmer's own rows, all sent together
           every time one row is saved): caught by the `seen` dict below,
           no DB round trip needed.
        2. Against everything else already saved anywhere — a different
           farmer's animal, or one already approved into the register: the
           `ear_tag_used_by_other_animal` DB check, which excludes this
           submission's own rows so re-saving an animal you already
           registered isn't flagged as a duplicate of itself.

        `submission_id` is also passed through: the Livestock Details
        dialog's own rows never carry internal_record_id at all (it isn't one
        of the dialog's configured columns), so a row already saved once in
        this same draft resubmits id-less on every later save. Without also
        excluding by submission_id, that row's earlier copy in
        g2p_intake_form_animals gets found and reported as belonging to "a
        different animal", permanently blocking Next on revisiting the
        section unless the ear tag is changed. See that function's docstring
        for why this scoping is safe.
        """
        self_ids = {
            str(record["internal_record_id"])
            for record in records
            if record.get("internal_record_id")
        }
        submission_id = next(
            (record.get("submission_id") for record in records if record.get("submission_id")), None
        )

        seen: dict[tuple, str] = {}
        for record in records:
            ear_tag_id = record.get("ear_tag_id")
            if is_blank(ear_tag_id):
                continue
            key = (ear_tag_id, record.get("species"), record.get("breed"))
            if key in seen:
                validation_error(
                    f"ear_tag_id '{ear_tag_id}' is used by more than one animal of the "
                    "same species and breed in this record."
                )
            seen[key] = ear_tag_id

            if await ear_tag_used_by_other_animal(
                ear_tag_id,
                record.get("species"),
                record.get("breed"),
                exclude_internal_record_ids=self_ids,
                exclude_submission_id=submission_id,
            ):
                validation_error(
                    f"ear_tag_id '{ear_tag_id}' is already registered to a different "
                    "animal of the same species and breed."
                )

    async def _validate_no_duplicate_secondary_identifiers(self, records: list[dict]) -> None:
        """Same protection as _validate_no_duplicate_ear_tags, for the
        secondary_identifier animals of a species whose "Requires Ear Tag"
        config is off use instead of an ear tag. A blank secondary_identifier
        is skipped here the same way a blank ear_tag_id is — an ear-tagged
        species' record simply never has one, and _validate_identifier_required
        already rejected a missing one for a species that needed it before
        this runs.

        Also scoped by submission_id, for the same reason
        _validate_no_duplicate_ear_tags is — see that method's and
        secondary_identifier_used_by_other_animal's docstrings.
        """
        self_ids = {
            str(record["internal_record_id"])
            for record in records
            if record.get("internal_record_id")
        }
        submission_id = next(
            (record.get("submission_id") for record in records if record.get("submission_id")), None
        )

        seen: dict[tuple, str] = {}
        for record in records:
            secondary_identifier = record.get("secondary_identifier")
            if is_blank(secondary_identifier):
                continue
            key = (secondary_identifier, record.get("species"), record.get("breed"))
            if key in seen:
                validation_error(
                    f"secondary_identifier '{secondary_identifier}' is used by more "
                    "than one animal of the same species and breed in this record."
                )
            seen[key] = secondary_identifier

            if await secondary_identifier_used_by_other_animal(
                secondary_identifier,
                record.get("species"),
                record.get("breed"),
                exclude_internal_record_ids=self_ids,
                exclude_submission_id=submission_id,
            ):
                validation_error(
                    f"secondary_identifier '{secondary_identifier}' is already "
                    "registered to a different animal of the same species and breed."
                )

    def _validate_not_in_future(self, record: dict, field: str) -> None:
        value = parse_date(record.get(field))
        if value is not None and value > date.today():
            validation_error(f"{field} must not be in the future")

    def _validate_weight(self, record: dict) -> None:
        weight = as_float(record.get("weight"))
        if weight is not None and weight <= 0:
            validation_error("weight must be greater than zero")

    def _populate_age_from_date_of_birth(self, record: dict) -> None:
        """Derive the stored Age display string from date_of_birth, the same
        way `g2p.livestock.registry.line._compute_age` did in the Odoo module.
        Overwrites whatever was submitted for "age" — it is a display value
        derived from date_of_birth, not independent input.
        """
        birth_date = parse_date(record.get("date_of_birth"))
        if birth_date is None:
            record["age"] = None
            return
        years, months = self._calculate_age_years_months(birth_date)
        record["age"] = f"{years} years, {months} months"

    @staticmethod
    def _calculate_age_years_months(birth_date: date) -> tuple[int, int]:
        today = date.today()
        years = today.year - birth_date.year
        months = today.month - birth_date.month
        if today.day < birth_date.day:
            months -= 1
        if months < 0:
            years -= 1
            months += 12
        return years, months

    def construct_search_text(self, payload: dict, extra: list[str] = None) -> str:
        _logger.info("Constructing search text for animal record")

        keys = [
            "functional_record_id",
            "ear_tag_id",
            "secondary_identifier",
            "animal_name",
            "species",
            "breed",
            "gender",
            "health_status",
            "vaccination_status",
            "state",
        ]
        search_text = []
        if extra:
            search_text.extend(str(item).strip() for item in extra if str(item).strip())
        search_text.extend(
            str(payload.get(key) or "").strip()
            for key in keys
            if str(payload.get(key) or "").strip()
        )

        return " ".join(search_text).strip()

    def construct_record_name(self, payload: dict, extra: list[str] = None) -> str:
        _logger.info("Constructing record name for animal record")

        # ear_tag_id is blank for a species that doesn't require one (e.g.
        # poultry, beehive) — fall back to secondary_identifier so those
        # records still get a distinguishing name instead of just the bare
        # species.
        identifier = payload.get("ear_tag_id") or payload.get("secondary_identifier")
        record_name = []
        if extra:
            record_name.extend(str(item).strip() for item in extra if str(item).strip())
        # A flock-species row stands for a headcount, not one animal — lead
        # with "<quantity> x " so the record name reads as "500 x FLOCK-A
        # Poultry" instead of implying a single bird. quantity is only ever
        # populated for a flock-species row (_validate_quantity requires it
        # there and nowhere else), so its presence alone is a reliable,
        # purely local flock signal — no need for an async species-config
        # lookup in this synchronous method (construct_record_name /
        # construct_search_text are called from sync model methods; see
        # models/animal.py's get_record_name_fields).
        quantity = payload.get("quantity")
        if quantity not in (None, ""):
            record_name.append(f"{quantity} x")
        if identifier and str(identifier).strip():
            record_name.append(str(identifier).strip())
        species = payload.get("species")
        if species and str(species).strip():
            record_name.append(str(species).strip())

        return " ".join(record_name).strip()
