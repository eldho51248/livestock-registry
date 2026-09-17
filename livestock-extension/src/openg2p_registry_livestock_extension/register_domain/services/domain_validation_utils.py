from datetime import date, datetime

from openg2p_registry_core.errors import G2PRegistryErrorCodes, G2PRegistryException


def validation_error(message: str) -> None:
    raise G2PRegistryException(
        code=G2PRegistryErrorCodes.REQUEST_VALIDATION_ERROR.value[1],
        message=message,
    )


def parse_date(value) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
        except ValueError:
            pass
        for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d"):
            try:
                return datetime.strptime(value, fmt).date()
            except ValueError:
                continue
    return None


def as_int(value) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def as_float(value) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def as_bool(value) -> bool | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in {"true", "1", "yes"}:
            return True
        if normalized in {"false", "0", "no"}:
            return False
    return bool(value)


def is_blank(value) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, dict, tuple, set)):
        return len(value) == 0
    return False


def require_field(record: dict, field: str, label: str | None = None) -> None:
    """Reject the save outright if field is missing/blank. Enforced here
    server-side rather than only via "widget-required" in the form's JSON,
    since a required-but-empty field is something the backend can always
    catch reliably — unlike display quirks in the table-cell widgets, which
    this project found are not something we can trust the frontend to get
    right without source access to fix them.
    """
    if is_blank(record.get(field)):
        validation_error(f"{label or field} is required")


def _animal_models():
    """Import the animal models the same way the platform itself resolves
    the domain extension: through the "openg2p_registry_extensions" alias
    that main.py points at this package's real module in sys.modules
    (Option C), not through this package's own real dotted name.

    Importing via "..models" instead loads a second, independent copy of
    every model under a different sys.modules key — same source file, but a
    distinct module object — and SQLAlchemy then refuses the second
    declarative Table registration ("... is already defined for this
    MetaData instance"). Importing here, not at module load: only needed by
    the two DB-touching functions below, and doing it lazily avoids forcing
    load order relative to app startup.
    """
    import importlib

    models = importlib.import_module("openg2p_registry_extensions.register_domain.models")
    return models.G2PRegisterAnimal, models.G2PIntakeFormAnimal


async def ear_tag_exists(ear_tag_id: str) -> bool:
    """True if ear_tag_id belongs to a real animal — already approved into the
    register, or drafted under some in-progress intake submission.

    This is a global existence check only, NOT scoped to the farmer/record
    being edited: validate_domain_attributes (the caller) is only handed this
    section's own rows by the platform, with no link back to which
    submission or register record they belong to. So a real ear tag typed
    from a *different* farmer's animals will still pass. It still catches
    typos and made-up tags, which is the bulk of the risk a free-text field
    carries.
    """
    if is_blank(ear_tag_id):
        return False

    from openg2p_fastapi_common.context import dbengine
    from sqlalchemy import exists, select
    from sqlalchemy.ext.asyncio import async_sessionmaker

    G2PRegisterAnimal, G2PIntakeFormAnimal = _animal_models()

    session_maker = async_sessionmaker(dbengine.get(), expire_on_commit=False)
    async with session_maker() as session:
        in_register = (
            await session.execute(select(exists().where(G2PRegisterAnimal.ear_tag_id == ear_tag_id)))
        ).scalar()
        if in_register:
            return True
        in_intake = (
            await session.execute(select(exists().where(G2PIntakeFormAnimal.ear_tag_id == ear_tag_id)))
        ).scalar()
        return bool(in_intake)


async def ear_tag_used_by_other_animal(
    ear_tag_id: str,
    species,
    breed,
    exclude_internal_record_ids: set[str] | None = None,
    exclude_submission_id: str | None = None,
) -> bool:
    """True if `ear_tag_id`, with this same species and breed, already
    belongs to a DIFFERENT animal — either already approved into the
    register, or drafted under some other in-progress intake submission.
    Mirrors the Old System's duplicate check ("same tag + same species +
    same breed already used"), which Gen2's Livestock Details section was
    missing entirely — see `_validate_no_duplicate_ear_tags` in
    G2PRegisterDomainServiceAnimal, the only caller.

    Scoped to the record being edited on BOTH tables:
    `exclude_internal_record_ids` should be every internal_record_id already
    present in the current save's own row list. This matters just as much
    for g2p_register_animals as for g2p_intake_form_animals — editing an
    already-approved animal's *other* fields (e.g. health_status) resubmits
    its unchanged ear_tag/species/breed, and without excluding its own
    internal_record_id that combination is always found "already registered"
    against itself, permanently blocking every edit to an approved animal
    that doesn't touch its ear tag. (Found via G2R-136 audit-log testing:
    editing Health Status on an already-approved animal raised
    "ear_tag_id ... is already registered to a different animal" even though
    nothing about the tag, species or breed had changed.)

    `exclude_submission_id` covers a second, DRAFT-only gap: the Livestock
    Details section's own "Add record" dialog builds each row from just its
    configured columns, so a row the frontend already saved once (as part of
    this same intake submission) resubmits with no internal_record_id at
    all — there's nowhere in that dialog's column config for one to ride
    along on. Without this, revisiting the section and clicking Next again
    (no edits) resends that same row id-less, `exclude_internal_record_ids`
    ends up empty, and the row's own already-saved g2p_intake_form_animals
    copy gets found and reported as "a different animal" — permanently
    blocking Next until the ear tag is changed to something that no longer
    matches. Scoping to this submission_id is safe here in a way it isn't for
    internal_record_id: a genuine same-tag/species/breed collision between two
    DIFFERENT animals within the very same submission is still caught by the
    `seen` dict in `_validate_no_duplicate_ear_tags`, which runs first and
    scopes purely to the current request's own row list, independent of the
    DB. Only ever applied to g2p_intake_form_animals — g2p_register_animals
    rows have no submission_id to match against.
    """
    if is_blank(ear_tag_id):
        return False

    from openg2p_fastapi_common.context import dbengine
    from sqlalchemy import and_, exists, select
    from sqlalchemy.ext.asyncio import async_sessionmaker

    G2PRegisterAnimal, G2PIntakeFormAnimal = _animal_models()
    exclude_internal_record_ids = exclude_internal_record_ids or set()

    def _same_animal_key(model, *, scope_to_submission=False):
        conditions = [
            model.ear_tag_id == ear_tag_id,
            model.species == species,
            model.breed == breed,
        ]
        if exclude_internal_record_ids:
            conditions.append(model.internal_record_id.not_in(exclude_internal_record_ids))
        if scope_to_submission and exclude_submission_id:
            conditions.append(model.submission_id != exclude_submission_id)
        return and_(*conditions)

    session_maker = async_sessionmaker(dbengine.get(), expire_on_commit=False)
    async with session_maker() as session:
        in_register = (
            await session.execute(select(exists().where(_same_animal_key(G2PRegisterAnimal))))
        ).scalar()
        if in_register:
            return True

        in_intake = (
            await session.execute(
                select(exists().where(_same_animal_key(G2PIntakeFormAnimal, scope_to_submission=True)))
            )
        ).scalar()
        return bool(in_intake)


async def secondary_identifier_used_by_other_animal(
    secondary_identifier: str,
    species,
    breed,
    exclude_internal_record_ids: set[str] | None = None,
    exclude_submission_id: str | None = None,
) -> bool:
    """Same check as ear_tag_used_by_other_animal, for `secondary_identifier`
    — the leg band/wing tag/hive number an _EAR_TAG_EXEMPT_SPECIES animal
    (poultry, beehive; see G2PRegisterDomainServiceAnimal) identifies by
    instead of an ear tag. Kept as a separate function rather than a
    parameterized field name so each stays a straightforward, obviously
    correct mirror of the other — see that function's docstring for why the
    exclude_internal_record_ids and exclude_submission_id scoping (and the
    internal_record_id one's ear-tag-only caveat) matter.
    """
    if is_blank(secondary_identifier):
        return False

    from openg2p_fastapi_common.context import dbengine
    from sqlalchemy import and_, exists, select
    from sqlalchemy.ext.asyncio import async_sessionmaker

    G2PRegisterAnimal, G2PIntakeFormAnimal = _animal_models()
    exclude_internal_record_ids = exclude_internal_record_ids or set()

    def _same_animal_key(model, *, scope_to_submission=False):
        conditions = [
            model.secondary_identifier == secondary_identifier,
            model.species == species,
            model.breed == breed,
        ]
        if exclude_internal_record_ids:
            conditions.append(model.internal_record_id.not_in(exclude_internal_record_ids))
        if scope_to_submission and exclude_submission_id:
            conditions.append(model.submission_id != exclude_submission_id)
        return and_(*conditions)

    session_maker = async_sessionmaker(dbengine.get(), expire_on_commit=False)
    async with session_maker() as session:
        in_register = (
            await session.execute(select(exists().where(_same_animal_key(G2PRegisterAnimal))))
        ).scalar()
        if in_register:
            return True

        in_intake = (
            await session.execute(
                select(exists().where(_same_animal_key(G2PIntakeFormAnimal, scope_to_submission=True)))
            )
        ).scalar()
        return bool(in_intake)


async def get_animal_species(ear_tag_id: str) -> str | None:
    """The species already recorded against ear_tag_id under Livestock
    Details, or None if the ear tag isn't known anywhere. Checks the
    approved register first (authoritative), then falls back to any
    in-progress intake draft.

    Same scoping caveat as ear_tag_exists: this is a global lookup by ear
    tag, not scoped to the farmer/record currently being edited.
    """
    if is_blank(ear_tag_id):
        return None

    from openg2p_fastapi_common.context import dbengine
    from sqlalchemy import and_, select
    from sqlalchemy.ext.asyncio import async_sessionmaker

    G2PRegisterAnimal, G2PIntakeFormAnimal = _animal_models()

    def _has_species(model):
        # Excluded in the WHERE clause, not just checked after fetching: the
        # same ear tag can legitimately appear on more than one row (repeat
        # test submissions, a farmer's animal re-entered in a later intake),
        # and without this an unordered .limit(1) can just as easily land on
        # a row where species was never filled in, making the result
        # nondeterministic — same ear tag, different answer between calls.
        return and_(model.ear_tag_id == ear_tag_id, model.species.is_not(None), model.species != "")

    session_maker = async_sessionmaker(dbengine.get(), expire_on_commit=False)
    async with session_maker() as session:
        species = (
            await session.execute(
                select(G2PRegisterAnimal.species)
                .where(_has_species(G2PRegisterAnimal))
                .order_by(G2PRegisterAnimal.created_at.desc())
                .limit(1)
            )
        ).scalar()
        if species:
            return species
        species = (
            await session.execute(
                select(G2PIntakeFormAnimal.species)
                .where(_has_species(G2PIntakeFormAnimal))
                .order_by(G2PIntakeFormAnimal.created_at.desc())
                .limit(1)
            )
        ).scalar()
        return species


async def humanize_attribute_value(value_id: str | None) -> str:
    """The human-readable label for an attribute value id (e.g.
    "LIVESTOCK_SPECIES_SHEEP" -> "Sheep"), for building a validation message
    a user can actually act on. Falls back to the raw id if it isn't a known
    attribute value (or is blank) — validation error text should never go
    silent just because a lookup came up empty.
    """
    if is_blank(value_id):
        return str(value_id)

    from openg2p_fastapi_common.context import dbengine
    from openg2p_registry_core.models import G2PAttributeValue
    from sqlalchemy import select
    from sqlalchemy.ext.asyncio import async_sessionmaker

    session_maker = async_sessionmaker(dbengine.get(), expire_on_commit=False)
    async with session_maker() as session:
        display = (
            await session.execute(
                select(G2PAttributeValue.value_display).where(G2PAttributeValue.value_id == value_id)
            )
        ).scalar()
        return display or value_id


async def get_species_config(species_value_id: str | None) -> tuple[bool, bool]:
    """(requires_ear_tag, is_flock_species) for a LIVESTOCK_SPECIES value —
    e.g. Poultry/Beehive vs. Cattle/Sheep/... — configurable per species from
    Configuration > Attributes > Species (an Edit Attribute Value's "Requires
    Ear Tag" / "Flock / Group Species" checkboxes), not a hardcoded species
    list in this codebase. Backed by G2PAttributeValueSpeciesConfig, a
    per-value side table (see core-patches/apply_patches.py Fix 4) the same
    way G2PAttributeValueSchedule already backs per-value vaccine scheduling
    — most species (and every non-species attribute value) never get a row
    there, which is why every field on it is nullable.

    Defaults to (True, False) — ear-tag-required, not a flock — whenever no
    row exists (species left blank, a species nobody has configured yet, or
    a brand-new species just added in Configuration). That default matches
    every species' actual behavior before this table existed, so an
    unconfigured species behaves exactly as before rather than silently
    losing its ear-tag requirement.
    """
    requires_ear_tag, is_flock_species = True, False
    if is_blank(species_value_id):
        return requires_ear_tag, is_flock_species

    from openg2p_fastapi_common.context import dbengine
    from openg2p_registry_core.models import G2PAttributeValueSpeciesConfig
    from sqlalchemy.ext.asyncio import async_sessionmaker

    session_maker = async_sessionmaker(dbengine.get(), expire_on_commit=False)
    async with session_maker() as session:
        config = await session.get(G2PAttributeValueSpeciesConfig, species_value_id)
        if config is None:
            return requires_ear_tag, is_flock_species
        if config.requires_ear_tag is not None:
            requires_ear_tag = config.requires_ear_tag
        if config.is_flock_species is not None:
            is_flock_species = config.is_flock_species
        return requires_ear_tag, is_flock_species


async def validate_species_matches(record: dict) -> None:
    """If both ear_tag_id and species are filled in on this record, species
    must match what's already recorded for that ear tag under Livestock
    Details. Either one left blank is skipped, not rejected — this only
    catches a genuine mismatch, not an incomplete row (other validators
    handle required-field checks).
    """
    ear_tag_id = record.get("ear_tag_id")
    species = record.get("species")
    if is_blank(ear_tag_id) or is_blank(species):
        return

    animal_species = await get_animal_species(str(ear_tag_id).strip())
    if animal_species is None:
        # Nothing recorded to compare against (e.g. species was never filled
        # in under Livestock Details for this animal) — ear_tag_exists
        # already rejects an ear tag that isn't real at all, so this is not
        # this check's job to also flag.
        return

    if str(species).strip() != animal_species:
        entered_label = await humanize_attribute_value(species)
        actual_label = await humanize_attribute_value(animal_species)
        validation_error(
            f"species '{entered_label}' does not match ear tag '{ear_tag_id}', "
            f"which is recorded as '{actual_label}' under Livestock Details. "
            "Select the matching species, or check you entered the correct ear tag."
        )


# ─── Duplicate event checks (G2R-134) ────────────────────────────────────────
#
# The Old System refused to record the same event twice for one animal
# (`_check_duplicate_health_event` and friends in the Odoo module); Gen2 only
# had the ear-tag duplicate check above for the Animal section. The two
# helpers below give an event section the same two-layer check the Animal
# section already has: first within the rows of the current save, then
# against everything already in the register or drafted in any intake
# submission. What counts as "the same event" is decided by each section's
# own domain service, which passes the fields that must match. Used by the
# Health Event and Vaccination services here; the Vital Event (mortality /
# disease) and Breeding (21-day cycle) checks live in their own services
# with their own helpers.


def _event_models(register_mnemonic: str):
    """The (register, intake) model pair for an event section, e.g.
    "HealthEvent" -> (G2PRegisterHealthEvent, G2PIntakeFormHealthEvent).
    Imported through the "openg2p_registry_extensions" alias for the same
    reason _animal_models does: importing via "..models" would register a
    second copy of every table with SQLAlchemy.
    """
    import importlib

    models = importlib.import_module("openg2p_registry_extensions.register_domain.models")
    return (
        getattr(models, f"G2PRegister{register_mnemonic}"),
        getattr(models, f"G2PIntakeForm{register_mnemonic}"),
    )


def first_repeated_key(records: list[dict], key_of) -> tuple | None:
    """The first key that appears on more than one row of this save, or
    None. `key_of(record)` returns the tuple that identifies an event for
    duplicate purposes, or None to leave that row out (e.g. ear tag or date
    not filled in yet — required-field checks own those).
    """
    seen: set[tuple] = set()
    for record in records:
        key = key_of(record)
        if key is None:
            continue
        if key in seen:
            return key
        seen.add(key)
    return None


async def event_already_recorded(
    register_mnemonic: str,
    match: dict,
    exclude_internal_record_ids: set[str] | None = None,
    within_days: tuple | None = None,
) -> bool:
    """True if an event with these same field values already exists for
    this section — approved into the register, or drafted under any intake
    submission.

    `match` maps column name -> value that must be equal (a None value
    matches IS NULL, so "no disease recorded" is a value in its own right,
    not a wildcard). `within_days=(column, date, days)` adds a date-window
    condition instead of an exact date, for rules like the Old System's
    "no second breeding event of the same type within 21 days".

    `exclude_internal_record_ids` must be every internal_record_id already
    present in the current save's own rows, for the same reason as in
    ear_tag_used_by_other_animal: editing an already-approved event
    resubmits its unchanged key fields, and without excluding its own row it
    would always be found "already recorded" against itself.
    """
    from datetime import timedelta

    from openg2p_fastapi_common.context import dbengine
    from sqlalchemy import and_, exists, select
    from sqlalchemy.ext.asyncio import async_sessionmaker

    register_model, intake_model = _event_models(register_mnemonic)
    exclude_internal_record_ids = exclude_internal_record_ids or set()

    def _same_event(model):
        conditions = []
        for column, value in match.items():
            attribute = getattr(model, column)
            conditions.append(attribute.is_(None) if value is None else attribute == value)
        if within_days:
            column, on, days = within_days
            attribute = getattr(model, column)
            conditions.append(attribute.between(on - timedelta(days=days), on + timedelta(days=days)))
        if exclude_internal_record_ids:
            conditions.append(model.internal_record_id.not_in(exclude_internal_record_ids))
        return and_(*conditions)

    session_maker = async_sessionmaker(dbengine.get(), expire_on_commit=False)
    async with session_maker() as session:
        in_register = (
            await session.execute(select(exists().where(_same_event(register_model))))
        ).scalar()
        if in_register:
            return True

        in_intake = (
            await session.execute(select(exists().where(_same_event(intake_model))))
        ).scalar()
        return bool(in_intake)
