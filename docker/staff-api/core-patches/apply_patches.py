"""Applies our fixes to the base image's installed openg2p_registry_core at
build time — NOT a wholesale file replacement, which is unsafe here: this
image's registry-platform lineage has drifted from our local checkout of that
repo in places unrelated to these fixes (e.g. it lacks G2PAttributeValueRole,
uses a different data-policy service name), so overwriting whole files can
delete code this base image actually needs and crash the app on import. Every
patch below finds an exact, small, known-good substring already proven to
match this image's real file content and swaps in the minimal fix — the same
technique validated by hand against the running container before this was
baked into the Dockerfile, now applied automatically on every build so it
survives rebuilds instead of being silently lost.

Run at Docker build time only (see docker/staff-api/Dockerfile).
"""

BASE = "/usr/local/lib/python3.12/site-packages/openg2p_registry_core"


def apply(path, old, new, label):
    with open(path) as f:
        content = f.read()
    n = content.count(old)
    assert n == 1, f"{label}: expected 1 match in {path}, found {n}"
    content = content.replace(old, new)
    with open(path, "w") as f:
        f.write(content)
    print(f"OK: {label}")


# ─── Fix 1: allow a hierarchical attribute value's parent to come from a
# DIFFERENT attribute (e.g. a Breed's parent is a Species value, not another
# Breed) — the original check wrongly required the same attribute_id.
apply(
    f"{BASE}/services/g2p_attribute_service.py",
    '''        parent = await session.get(G2PAttributeValue, parent_value_id)
        if not parent or parent.attribute_id != attribute_id:
            self._raise_validation_error(
                f"parent_value_id '{parent_value_id}' was not found for attribute '{attribute_id}'"
            )''',
    '''        parent = await session.get(G2PAttributeValue, parent_value_id)
        if not parent:
            self._raise_validation_error(
                f"parent_value_id '{parent_value_id}' was not found"
            )''',
    "validate_parent_value: allow cross-attribute parent",
)

# ─── Fix 2: optional per-value scheduling metadata (Interval/Active/Notes),
# e.g. how many days between doses for a Vaccine attribute value.
apply(
    f"{BASE}/models/g2p_attributes.py",
    '''    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)''',
    '''    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class G2PAttributeValueSchedule(BaseORMModel):
    __tablename__ = "g2p_attribute_value_schedules"

    value_id: Mapped[str] = mapped_column(String, primary_key=True)
    interval_days: Mapped[int] = mapped_column(Integer, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=True)
    notes: Mapped[str] = mapped_column(String, nullable=True)''',
    "models/g2p_attributes.py: add G2PAttributeValueSchedule",
)

with open(f"{BASE}/models/__init__.py") as f:
    _models_init = f.read()
if "G2PAttributeValueRole" in _models_init:
    apply(
        f"{BASE}/models/__init__.py",
        "from .g2p_attributes import G2PAttribute, G2PAttributeValue, G2PAttributeValueRole",
        "from .g2p_attributes import G2PAttribute, G2PAttributeValue, G2PAttributeValueRole, G2PAttributeValueSchedule",
        "models/__init__.py: import (with Role)",
    )
else:
    apply(
        f"{BASE}/models/__init__.py",
        "from .g2p_attributes import G2PAttribute, G2PAttributeValue",
        "from .g2p_attributes import G2PAttribute, G2PAttributeValue, G2PAttributeValueSchedule",
        "models/__init__.py: import (without Role)",
    )

apply(
    f"{BASE}/schemas/register_payload.py",
    '''class AttributeValueData(BaseModel):
    value_id: str
    attribute_id: str
    value_code: str
    value_display: str
    parent_value_id: Optional[str] = None
    sort_order: int''',
    '''class AttributeValueData(BaseModel):
    value_id: str
    attribute_id: str
    value_code: str
    value_display: str
    parent_value_id: Optional[str] = None
    sort_order: int
    interval_days: Optional[int] = None
    is_active: Optional[bool] = None
    notes: Optional[str] = None''',
    "register_payload.py: AttributeValueData",
)
apply(
    f"{BASE}/schemas/register_payload.py",
    '''class CreateAttributeValueRequestPayload(BaseModel):
    attribute_id: str
    value_code: str
    value_display: str
    parent_value_id: Optional[str] = None
    sort_order: int = 0''',
    '''class CreateAttributeValueRequestPayload(BaseModel):
    attribute_id: str
    value_code: str
    value_display: str
    parent_value_id: Optional[str] = None
    sort_order: int = 0
    interval_days: Optional[int] = None
    is_active: Optional[bool] = None
    notes: Optional[str] = None''',
    "register_payload.py: CreateAttributeValueRequestPayload",
)
apply(
    f"{BASE}/schemas/register_payload.py",
    '''class UpdateAttributeValueRequestPayload(BaseModel):
    value_id: str
    value_code: Optional[str] = None
    value_display: Optional[str] = None
    parent_value_id: Optional[str] = None
    sort_order: Optional[int] = None''',
    '''class UpdateAttributeValueRequestPayload(BaseModel):
    value_id: str
    value_code: Optional[str] = None
    value_display: Optional[str] = None
    parent_value_id: Optional[str] = None
    sort_order: Optional[int] = None
    interval_days: Optional[int] = None
    is_active: Optional[bool] = None
    notes: Optional[str] = None''',
    "register_payload.py: UpdateAttributeValueRequestPayload",
)

apply(
    f"{BASE}/controller_services/attribute_controller_service.py",
    '''            attribute_value = await g2p_attribute_service.create_attribute_value(
                attribute_id=payload.attribute_id,
                value_code=payload.value_code,
                value_display=payload.value_display,
                parent_value_id=payload.parent_value_id,
                sort_order=payload.sort_order,
                session=session,
            )''',
    '''            attribute_value = await g2p_attribute_service.create_attribute_value(
                attribute_id=payload.attribute_id,
                value_code=payload.value_code,
                value_display=payload.value_display,
                parent_value_id=payload.parent_value_id,
                sort_order=payload.sort_order,
                interval_days=payload.interval_days,
                is_active=payload.is_active,
                notes=payload.notes,
                session=session,
            )''',
    "attribute_controller_service.py: create call",
)
apply(
    f"{BASE}/controller_services/attribute_controller_service.py",
    '''            attribute_value = await g2p_attribute_service.update_attribute_value(
                value_id=payload.value_id,
                value_code=payload.value_code,
                value_display=payload.value_display,
                parent_value_id=payload.parent_value_id,
                sort_order=payload.sort_order,
                session=session,
            )''',
    '''            attribute_value = await g2p_attribute_service.update_attribute_value(
                value_id=payload.value_id,
                value_code=payload.value_code,
                value_display=payload.value_display,
                parent_value_id=payload.parent_value_id,
                sort_order=payload.sort_order,
                interval_days=payload.interval_days,
                is_active=payload.is_active,
                notes=payload.notes,
                session=session,
            )''',
    "attribute_controller_service.py: update call",
)

with open(f"{BASE}/services/g2p_attribute_service.py") as f:
    _svc = f.read()
if "G2PAttributeValueRole" in _svc.split("\n")[11]:
    apply(
        f"{BASE}/services/g2p_attribute_service.py",
        "from ..models import G2PAttribute, G2PAttributeValue, G2PAttributeValueRole",
        "from ..models import G2PAttribute, G2PAttributeValue, G2PAttributeValueRole, G2PAttributeValueSchedule",
        "g2p_attribute_service.py: import (with Role)",
    )
else:
    apply(
        f"{BASE}/services/g2p_attribute_service.py",
        "from ..models import G2PAttribute, G2PAttributeValue",
        "from ..models import G2PAttribute, G2PAttributeValue, G2PAttributeValueSchedule",
        "g2p_attribute_service.py: import (without Role)",
    )

apply(
    f"{BASE}/services/g2p_attribute_service.py",
    '''            return [self._value_to_data(value) for value in result.scalars().all()], total''',
    '''            values = result.scalars().all()
            schedules = await self._get_schedules_by_value_ids(
                db_session, [v.value_id for v in values]
            )
            return [
                self._value_to_data(value, schedules.get(value.value_id))
                for value in values
            ], total''',
    "g2p_attribute_service.py: get_attribute_values return",
)

apply(
    f"{BASE}/services/g2p_attribute_service.py",
    '''    async def create_attribute_value(
        self,
        *,
        attribute_id: str,
        value_code: str,
        value_display: str,
        parent_value_id: Optional[str],
        sort_order: int,
        session: AsyncSession,
    ) -> AttributeValueData:''',
    '''    async def create_attribute_value(
        self,
        *,
        attribute_id: str,
        value_code: str,
        value_display: str,
        parent_value_id: Optional[str],
        sort_order: int,
        session: AsyncSession,
        interval_days: Optional[int] = None,
        is_active: Optional[bool] = None,
        notes: Optional[str] = None,
    ) -> AttributeValueData:''',
    "g2p_attribute_service.py: create_attribute_value signature",
)

apply(
    f"{BASE}/services/g2p_attribute_service.py",
    '''        session.add(value)
        await session.flush()
        await self._clear_attribute_cache()
        return self._value_to_data(value)

    async def update_attribute_value(
        self,
        *,
        value_id: str,
        value_code: Optional[str],
        value_display: Optional[str],
        parent_value_id: Optional[str],
        sort_order: Optional[int],
        session: AsyncSession,
    ) -> AttributeValueData:
        value = await session.get(G2PAttributeValue, value_id)
        if not value:
            self._raise_attribute_value_not_found(value_id)

        if all(field is None for field in (value_code, value_display, parent_value_id, sort_order)):
            self._raise_validation_error("At least one field must be provided to update")''',
    '''        session.add(value)

        schedule = await self._upsert_schedule(
            session,
            value_id=value.value_id,
            interval_days=interval_days,
            is_active=is_active,
            notes=notes,
        )

        await session.flush()
        await self._clear_attribute_cache()
        return self._value_to_data(value, schedule)

    async def update_attribute_value(
        self,
        *,
        value_id: str,
        value_code: Optional[str],
        value_display: Optional[str],
        parent_value_id: Optional[str],
        sort_order: Optional[int],
        session: AsyncSession,
        interval_days: Optional[int] = None,
        is_active: Optional[bool] = None,
        notes: Optional[str] = None,
    ) -> AttributeValueData:
        value = await session.get(G2PAttributeValue, value_id)
        if not value:
            self._raise_attribute_value_not_found(value_id)

        if all(
            field is None
            for field in (
                value_code, value_display, parent_value_id, sort_order,
                interval_days, is_active, notes,
            )
        ):
            self._raise_validation_error("At least one field must be provided to update")''',
    "g2p_attribute_service.py: create tail + update_attribute_value head",
)

apply(
    f"{BASE}/services/g2p_attribute_service.py",
    '''        session.add(value)
        await session.flush()
        await self._clear_attribute_cache()
        return self._value_to_data(value)

    async def delete_attribute_value(self, value_id: str, session: AsyncSession) -> str:
        value = await session.get(G2PAttributeValue, value_id)
        if not value:
            self._raise_attribute_value_not_found(value_id)

        if await self._child_value_count(session, value_id) > 0:
            raise G2PRegistryException(
                code=G2PRegistryErrorCodes.ATTRIBUTE_VALUE_HAS_CHILDREN.value[1],
                message=f"Cannot delete attribute value '{value_id}' while child values exist",
            )

        await session.delete(value)
        await session.flush()
        await self._clear_attribute_cache()
        return value_id''',
    '''        session.add(value)

        schedule = await self._upsert_schedule(
            session,
            value_id=value_id,
            interval_days=interval_days,
            is_active=is_active,
            notes=notes,
        )

        await session.flush()
        await self._clear_attribute_cache()
        return self._value_to_data(value, schedule)

    async def delete_attribute_value(self, value_id: str, session: AsyncSession) -> str:
        value = await session.get(G2PAttributeValue, value_id)
        if not value:
            self._raise_attribute_value_not_found(value_id)

        if await self._child_value_count(session, value_id) > 0:
            raise G2PRegistryException(
                code=G2PRegistryErrorCodes.ATTRIBUTE_VALUE_HAS_CHILDREN.value[1],
                message=f"Cannot delete attribute value '{value_id}' while child values exist",
            )

        schedule = await session.get(G2PAttributeValueSchedule, value_id)
        if schedule:
            await session.delete(schedule)

        await session.delete(value)
        await session.flush()
        await self._clear_attribute_cache()
        return value_id''',
    "g2p_attribute_service.py: update tail + delete_attribute_value",
)

apply(
    f"{BASE}/services/g2p_attribute_service.py",
    '''    def _value_to_data(self, value: G2PAttributeValue) -> AttributeValueData:
        return AttributeValueData(
            value_id=value.value_id,
            attribute_id=value.attribute_id,
            value_code=value.value_code,
            value_display=value.value_display,
            parent_value_id=value.parent_value_id,''',
    '''    async def _upsert_schedule(
        self,
        session: AsyncSession,
        *,
        value_id: str,
        interval_days: Optional[int],
        is_active: Optional[bool],
        notes: Optional[str],
    ) -> Optional["G2PAttributeValueSchedule"]:
        if interval_days is None and is_active is None and notes is None:
            return await session.get(G2PAttributeValueSchedule, value_id)

        schedule = await session.get(G2PAttributeValueSchedule, value_id)
        if not schedule:
            schedule = G2PAttributeValueSchedule(value_id=value_id)

        if interval_days is not None:
            schedule.interval_days = interval_days
        if is_active is not None:
            schedule.is_active = is_active
        if notes is not None:
            schedule.notes = notes

        session.add(schedule)
        return schedule

    async def _get_schedules_by_value_ids(self, session: AsyncSession, value_ids):
        if not value_ids:
            return {}
        query = select(G2PAttributeValueSchedule).where(
            G2PAttributeValueSchedule.value_id.in_(value_ids)
        )
        result = await session.execute(query)
        return {row.value_id: row for row in result.scalars().all()}

    def _value_to_data(self, value: G2PAttributeValue, schedule=None) -> AttributeValueData:
        return AttributeValueData(
            value_id=value.value_id,
            attribute_id=value.attribute_id,
            value_code=value.value_code,
            value_display=value.value_display,
            parent_value_id=value.parent_value_id,
            interval_days=schedule.interval_days if schedule else None,
            is_active=schedule.is_active if schedule else None,
            notes=schedule.notes if schedule else None,''',
    "g2p_attribute_service.py: _value_to_data + new helpers",
)

# ─── Fix 3: new domain-service extension hook, post_intake_upsert, called
# right after an intake-form section's records are upserted (staff clicking
# "Next"/save on that section) — well before the submission is approved or
# ingested. Added for G2PRegisterDomainServiceVitalEvent to reserve a Birth
# event's offspring ear tag(s) immediately, instead of only once the
# submission is later approved/ingested (see the livestock extension's
# g2p_register_domain_service_vital_event.py for the override).
apply(
    f"{BASE}/services/g2p_register_domain_service.py",
    '''    async def post_ingest(self, register_id: str, register_row, session: AsyncSession):
        pass''',
    '''    async def post_ingest(self, register_id: str, register_row, session: AsyncSession):
        pass

    async def post_intake_upsert(self, rows: list, session: AsyncSession) -> None:
        """Optional extension hook: runs right after an intake-form section's
        records have been upserted (and flushed) into the intake draft table
        -- i.e. when staff click "Next"/save on that section -- well before
        the submission is ever approved or ingested into the live register.
        `rows` are the just-upserted intake-draft ORM rows for that section.
        Override to enrich/mutate those still-draft rows (e.g. reserve an
        identifier ahead of time so it can be shown back to staff
        immediately). No-op by default."""
        pass''',
    "g2p_register_domain_service.py: add post_intake_upsert hook",
)

apply(
    f"{BASE}/services/intake_form_data_service.py",
    '''        existing_rows = await self._get_intake_rows(intake_class, submission.submission_id, session)
        incoming_ids = await self._upsert_intake_rows(
            intake_class,
            submission,
            section_payload or [],
            existing_rows,
            created_by,
            session,
        )
        await self._delete_missing_intake_rows(existing_rows, incoming_ids, session)''',
    '''        existing_rows = await self._get_intake_rows(intake_class, submission.submission_id, session)
        incoming_ids = await self._upsert_intake_rows(
            intake_class,
            submission,
            section_payload or [],
            existing_rows,
            created_by,
            session,
        )

        if domain_service and incoming_ids:
            upserted_rows = [
                row
                for row in await self._get_intake_rows_list(intake_class, submission.submission_id, session)
                if row.internal_record_id in incoming_ids
            ]
            # Runs while the section is still just an intake draft -- i.e. as
            # soon as staff save/"Next" this section, well before the
            # submission is approved or ingested.
            await domain_service.post_intake_upsert(upserted_rows, session)
            await session.flush()

        await self._delete_missing_intake_rows(existing_rows, incoming_ids, session)''',
    "intake_form_data_service.py: call post_intake_upsert after section save",
)

# ─── Fix 4: optional per-value species config (Requires Ear Tag / Flock
# Species) — same shape as Fix 2's scheduling metadata, for a completely
# different concern: whether an animal species is identified by an ear tag
# or a secondary_identifier, and whether it's recorded per-individual or as
# a headcounted flock. See the livestock extension's
# g2p_register_domain_service_animal.py (_species_requires_ear_tag /
# _species_is_flock, replacing the old hardcoded _EAR_TAG_EXEMPT_SPECIES /
# _FLOCK_SPECIES sets) for the only consumer. Chained onto Fix 2's own
# output text throughout, the same way Fix 3 above is unrelated to Fix 1/2 —
# each apply() below matches what Fix 2 already produced, not the pristine
# original file.
apply(
    f"{BASE}/models/g2p_attributes.py",
    '''class G2PAttributeValueSchedule(BaseORMModel):
    __tablename__ = "g2p_attribute_value_schedules"

    value_id: Mapped[str] = mapped_column(String, primary_key=True)
    interval_days: Mapped[int] = mapped_column(Integer, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=True)
    notes: Mapped[str] = mapped_column(String, nullable=True)''',
    '''class G2PAttributeValueSchedule(BaseORMModel):
    __tablename__ = "g2p_attribute_value_schedules"

    value_id: Mapped[str] = mapped_column(String, primary_key=True)
    interval_days: Mapped[int] = mapped_column(Integer, nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=True)
    notes: Mapped[str] = mapped_column(String, nullable=True)


class G2PAttributeValueSpeciesConfig(BaseORMModel):
    __tablename__ = "g2p_attribute_value_species_configs"

    value_id: Mapped[str] = mapped_column(String, primary_key=True)
    requires_ear_tag: Mapped[bool] = mapped_column(Boolean, nullable=True)
    is_flock_species: Mapped[bool] = mapped_column(Boolean, nullable=True)''',
    "models/g2p_attributes.py: add G2PAttributeValueSpeciesConfig",
)

apply(
    f"{BASE}/models/__init__.py",
    "G2PAttributeValueSchedule",
    "G2PAttributeValueSchedule, G2PAttributeValueSpeciesConfig",
    "models/__init__.py: import SpeciesConfig",
)

apply(
    f"{BASE}/schemas/register_payload.py",
    '''class AttributeValueData(BaseModel):
    value_id: str
    attribute_id: str
    value_code: str
    value_display: str
    parent_value_id: Optional[str] = None
    sort_order: int
    interval_days: Optional[int] = None
    is_active: Optional[bool] = None
    notes: Optional[str] = None''',
    '''class AttributeValueData(BaseModel):
    value_id: str
    attribute_id: str
    value_code: str
    value_display: str
    parent_value_id: Optional[str] = None
    sort_order: int
    interval_days: Optional[int] = None
    is_active: Optional[bool] = None
    notes: Optional[str] = None
    requires_ear_tag: Optional[bool] = None
    is_flock_species: Optional[bool] = None''',
    "register_payload.py: AttributeValueData + species config",
)
apply(
    f"{BASE}/schemas/register_payload.py",
    '''class CreateAttributeValueRequestPayload(BaseModel):
    attribute_id: str
    value_code: str
    value_display: str
    parent_value_id: Optional[str] = None
    sort_order: int = 0
    interval_days: Optional[int] = None
    is_active: Optional[bool] = None
    notes: Optional[str] = None''',
    '''class CreateAttributeValueRequestPayload(BaseModel):
    attribute_id: str
    value_code: str
    value_display: str
    parent_value_id: Optional[str] = None
    sort_order: int = 0
    interval_days: Optional[int] = None
    is_active: Optional[bool] = None
    notes: Optional[str] = None
    requires_ear_tag: Optional[bool] = None
    is_flock_species: Optional[bool] = None''',
    "register_payload.py: CreateAttributeValueRequestPayload + species config",
)
apply(
    f"{BASE}/schemas/register_payload.py",
    '''class UpdateAttributeValueRequestPayload(BaseModel):
    value_id: str
    value_code: Optional[str] = None
    value_display: Optional[str] = None
    parent_value_id: Optional[str] = None
    sort_order: Optional[int] = None
    interval_days: Optional[int] = None
    is_active: Optional[bool] = None
    notes: Optional[str] = None''',
    '''class UpdateAttributeValueRequestPayload(BaseModel):
    value_id: str
    value_code: Optional[str] = None
    value_display: Optional[str] = None
    parent_value_id: Optional[str] = None
    sort_order: Optional[int] = None
    interval_days: Optional[int] = None
    is_active: Optional[bool] = None
    notes: Optional[str] = None
    requires_ear_tag: Optional[bool] = None
    is_flock_species: Optional[bool] = None''',
    "register_payload.py: UpdateAttributeValueRequestPayload + species config",
)

apply(
    f"{BASE}/controller_services/attribute_controller_service.py",
    '''            attribute_value = await g2p_attribute_service.create_attribute_value(
                attribute_id=payload.attribute_id,
                value_code=payload.value_code,
                value_display=payload.value_display,
                parent_value_id=payload.parent_value_id,
                sort_order=payload.sort_order,
                interval_days=payload.interval_days,
                is_active=payload.is_active,
                notes=payload.notes,
                session=session,
            )''',
    '''            attribute_value = await g2p_attribute_service.create_attribute_value(
                attribute_id=payload.attribute_id,
                value_code=payload.value_code,
                value_display=payload.value_display,
                parent_value_id=payload.parent_value_id,
                sort_order=payload.sort_order,
                interval_days=payload.interval_days,
                is_active=payload.is_active,
                notes=payload.notes,
                requires_ear_tag=payload.requires_ear_tag,
                is_flock_species=payload.is_flock_species,
                session=session,
            )''',
    "attribute_controller_service.py: create call + species config",
)
apply(
    f"{BASE}/controller_services/attribute_controller_service.py",
    '''            attribute_value = await g2p_attribute_service.update_attribute_value(
                value_id=payload.value_id,
                value_code=payload.value_code,
                value_display=payload.value_display,
                parent_value_id=payload.parent_value_id,
                sort_order=payload.sort_order,
                interval_days=payload.interval_days,
                is_active=payload.is_active,
                notes=payload.notes,
                session=session,
            )''',
    '''            attribute_value = await g2p_attribute_service.update_attribute_value(
                value_id=payload.value_id,
                value_code=payload.value_code,
                value_display=payload.value_display,
                parent_value_id=payload.parent_value_id,
                sort_order=payload.sort_order,
                interval_days=payload.interval_days,
                is_active=payload.is_active,
                notes=payload.notes,
                requires_ear_tag=payload.requires_ear_tag,
                is_flock_species=payload.is_flock_species,
                session=session,
            )''',
    "attribute_controller_service.py: update call + species config",
)

with open(f"{BASE}/services/g2p_attribute_service.py") as f:
    _svc4 = f.read()
if "from ..models import G2PAttribute, G2PAttributeValue, G2PAttributeValueRole, G2PAttributeValueSchedule" in _svc4:
    apply(
        f"{BASE}/services/g2p_attribute_service.py",
        "from ..models import G2PAttribute, G2PAttributeValue, G2PAttributeValueRole, G2PAttributeValueSchedule",
        "from ..models import G2PAttribute, G2PAttributeValue, G2PAttributeValueRole, G2PAttributeValueSchedule, G2PAttributeValueSpeciesConfig",
        "g2p_attribute_service.py: import (with Role) + SpeciesConfig",
    )
else:
    apply(
        f"{BASE}/services/g2p_attribute_service.py",
        "from ..models import G2PAttribute, G2PAttributeValue, G2PAttributeValueSchedule",
        "from ..models import G2PAttribute, G2PAttributeValue, G2PAttributeValueSchedule, G2PAttributeValueSpeciesConfig",
        "g2p_attribute_service.py: import (without Role) + SpeciesConfig",
    )

apply(
    f"{BASE}/services/g2p_attribute_service.py",
    '''            values = result.scalars().all()
            schedules = await self._get_schedules_by_value_ids(
                db_session, [v.value_id for v in values]
            )
            return [
                self._value_to_data(value, schedules.get(value.value_id))
                for value in values
            ], total''',
    '''            values = result.scalars().all()
            schedules = await self._get_schedules_by_value_ids(
                db_session, [v.value_id for v in values]
            )
            species_configs = await self._get_species_configs_by_value_ids(
                db_session, [v.value_id for v in values]
            )
            return [
                self._value_to_data(
                    value,
                    schedules.get(value.value_id),
                    species_configs.get(value.value_id),
                )
                for value in values
            ], total''',
    "g2p_attribute_service.py: get_attribute_values return + species config",
)

apply(
    f"{BASE}/services/g2p_attribute_service.py",
    '''    async def create_attribute_value(
        self,
        *,
        attribute_id: str,
        value_code: str,
        value_display: str,
        parent_value_id: Optional[str],
        sort_order: int,
        session: AsyncSession,
        interval_days: Optional[int] = None,
        is_active: Optional[bool] = None,
        notes: Optional[str] = None,
    ) -> AttributeValueData:''',
    '''    async def create_attribute_value(
        self,
        *,
        attribute_id: str,
        value_code: str,
        value_display: str,
        parent_value_id: Optional[str],
        sort_order: int,
        session: AsyncSession,
        interval_days: Optional[int] = None,
        is_active: Optional[bool] = None,
        notes: Optional[str] = None,
        requires_ear_tag: Optional[bool] = None,
        is_flock_species: Optional[bool] = None,
    ) -> AttributeValueData:''',
    "g2p_attribute_service.py: create_attribute_value signature + species config",
)

apply(
    f"{BASE}/services/g2p_attribute_service.py",
    '''        session.add(value)

        schedule = await self._upsert_schedule(
            session,
            value_id=value.value_id,
            interval_days=interval_days,
            is_active=is_active,
            notes=notes,
        )

        await session.flush()
        await self._clear_attribute_cache()
        return self._value_to_data(value, schedule)

    async def update_attribute_value(
        self,
        *,
        value_id: str,
        value_code: Optional[str],
        value_display: Optional[str],
        parent_value_id: Optional[str],
        sort_order: Optional[int],
        session: AsyncSession,
        interval_days: Optional[int] = None,
        is_active: Optional[bool] = None,
        notes: Optional[str] = None,
    ) -> AttributeValueData:
        value = await session.get(G2PAttributeValue, value_id)
        if not value:
            self._raise_attribute_value_not_found(value_id)

        if all(
            field is None
            for field in (
                value_code, value_display, parent_value_id, sort_order,
                interval_days, is_active, notes,
            )
        ):
            self._raise_validation_error("At least one field must be provided to update")''',
    '''        session.add(value)

        schedule = await self._upsert_schedule(
            session,
            value_id=value.value_id,
            interval_days=interval_days,
            is_active=is_active,
            notes=notes,
        )
        species_config = await self._upsert_species_config(
            session,
            value_id=value.value_id,
            requires_ear_tag=requires_ear_tag,
            is_flock_species=is_flock_species,
        )

        await session.flush()
        await self._clear_attribute_cache()
        return self._value_to_data(value, schedule, species_config)

    async def update_attribute_value(
        self,
        *,
        value_id: str,
        value_code: Optional[str],
        value_display: Optional[str],
        parent_value_id: Optional[str],
        sort_order: Optional[int],
        session: AsyncSession,
        interval_days: Optional[int] = None,
        is_active: Optional[bool] = None,
        notes: Optional[str] = None,
        requires_ear_tag: Optional[bool] = None,
        is_flock_species: Optional[bool] = None,
    ) -> AttributeValueData:
        value = await session.get(G2PAttributeValue, value_id)
        if not value:
            self._raise_attribute_value_not_found(value_id)

        if all(
            field is None
            for field in (
                value_code, value_display, parent_value_id, sort_order,
                interval_days, is_active, notes,
                requires_ear_tag, is_flock_species,
            )
        ):
            self._raise_validation_error("At least one field must be provided to update")''',
    "g2p_attribute_service.py: create tail + update head + species config",
)

apply(
    f"{BASE}/services/g2p_attribute_service.py",
    '''        session.add(value)

        schedule = await self._upsert_schedule(
            session,
            value_id=value_id,
            interval_days=interval_days,
            is_active=is_active,
            notes=notes,
        )

        await session.flush()
        await self._clear_attribute_cache()
        return self._value_to_data(value, schedule)

    async def delete_attribute_value(self, value_id: str, session: AsyncSession) -> str:
        value = await session.get(G2PAttributeValue, value_id)
        if not value:
            self._raise_attribute_value_not_found(value_id)

        if await self._child_value_count(session, value_id) > 0:
            raise G2PRegistryException(
                code=G2PRegistryErrorCodes.ATTRIBUTE_VALUE_HAS_CHILDREN.value[1],
                message=f"Cannot delete attribute value '{value_id}' while child values exist",
            )

        schedule = await session.get(G2PAttributeValueSchedule, value_id)
        if schedule:
            await session.delete(schedule)

        await session.delete(value)
        await session.flush()
        await self._clear_attribute_cache()
        return value_id''',
    '''        session.add(value)

        schedule = await self._upsert_schedule(
            session,
            value_id=value_id,
            interval_days=interval_days,
            is_active=is_active,
            notes=notes,
        )
        species_config = await self._upsert_species_config(
            session,
            value_id=value_id,
            requires_ear_tag=requires_ear_tag,
            is_flock_species=is_flock_species,
        )

        await session.flush()
        await self._clear_attribute_cache()
        return self._value_to_data(value, schedule, species_config)

    async def delete_attribute_value(self, value_id: str, session: AsyncSession) -> str:
        value = await session.get(G2PAttributeValue, value_id)
        if not value:
            self._raise_attribute_value_not_found(value_id)

        if await self._child_value_count(session, value_id) > 0:
            raise G2PRegistryException(
                code=G2PRegistryErrorCodes.ATTRIBUTE_VALUE_HAS_CHILDREN.value[1],
                message=f"Cannot delete attribute value '{value_id}' while child values exist",
            )

        schedule = await session.get(G2PAttributeValueSchedule, value_id)
        if schedule:
            await session.delete(schedule)

        species_config = await session.get(G2PAttributeValueSpeciesConfig, value_id)
        if species_config:
            await session.delete(species_config)

        await session.delete(value)
        await session.flush()
        await self._clear_attribute_cache()
        return value_id''',
    "g2p_attribute_service.py: update tail + delete + species config",
)

apply(
    f"{BASE}/services/g2p_attribute_service.py",
    '''    async def _upsert_schedule(
        self,
        session: AsyncSession,
        *,
        value_id: str,
        interval_days: Optional[int],
        is_active: Optional[bool],
        notes: Optional[str],
    ) -> Optional["G2PAttributeValueSchedule"]:
        if interval_days is None and is_active is None and notes is None:
            return await session.get(G2PAttributeValueSchedule, value_id)

        schedule = await session.get(G2PAttributeValueSchedule, value_id)
        if not schedule:
            schedule = G2PAttributeValueSchedule(value_id=value_id)

        if interval_days is not None:
            schedule.interval_days = interval_days
        if is_active is not None:
            schedule.is_active = is_active
        if notes is not None:
            schedule.notes = notes

        session.add(schedule)
        return schedule

    async def _get_schedules_by_value_ids(self, session: AsyncSession, value_ids):
        if not value_ids:
            return {}
        query = select(G2PAttributeValueSchedule).where(
            G2PAttributeValueSchedule.value_id.in_(value_ids)
        )
        result = await session.execute(query)
        return {row.value_id: row for row in result.scalars().all()}

    def _value_to_data(self, value: G2PAttributeValue, schedule=None) -> AttributeValueData:
        return AttributeValueData(
            value_id=value.value_id,
            attribute_id=value.attribute_id,
            value_code=value.value_code,
            value_display=value.value_display,
            parent_value_id=value.parent_value_id,
            interval_days=schedule.interval_days if schedule else None,
            is_active=schedule.is_active if schedule else None,
            notes=schedule.notes if schedule else None,''',
    '''    async def _upsert_schedule(
        self,
        session: AsyncSession,
        *,
        value_id: str,
        interval_days: Optional[int],
        is_active: Optional[bool],
        notes: Optional[str],
    ) -> Optional["G2PAttributeValueSchedule"]:
        if interval_days is None and is_active is None and notes is None:
            return await session.get(G2PAttributeValueSchedule, value_id)

        schedule = await session.get(G2PAttributeValueSchedule, value_id)
        if not schedule:
            schedule = G2PAttributeValueSchedule(value_id=value_id)

        if interval_days is not None:
            schedule.interval_days = interval_days
        if is_active is not None:
            schedule.is_active = is_active
        if notes is not None:
            schedule.notes = notes

        session.add(schedule)
        return schedule

    async def _get_schedules_by_value_ids(self, session: AsyncSession, value_ids):
        if not value_ids:
            return {}
        query = select(G2PAttributeValueSchedule).where(
            G2PAttributeValueSchedule.value_id.in_(value_ids)
        )
        result = await session.execute(query)
        return {row.value_id: row for row in result.scalars().all()}

    async def _upsert_species_config(
        self,
        session: AsyncSession,
        *,
        value_id: str,
        requires_ear_tag: Optional[bool],
        is_flock_species: Optional[bool],
    ) -> Optional["G2PAttributeValueSpeciesConfig"]:
        if requires_ear_tag is None and is_flock_species is None:
            return await session.get(G2PAttributeValueSpeciesConfig, value_id)

        species_config = await session.get(G2PAttributeValueSpeciesConfig, value_id)
        if not species_config:
            species_config = G2PAttributeValueSpeciesConfig(value_id=value_id)

        if requires_ear_tag is not None:
            species_config.requires_ear_tag = requires_ear_tag
        if is_flock_species is not None:
            species_config.is_flock_species = is_flock_species

        session.add(species_config)
        return species_config

    async def _get_species_configs_by_value_ids(self, session: AsyncSession, value_ids):
        if not value_ids:
            return {}
        query = select(G2PAttributeValueSpeciesConfig).where(
            G2PAttributeValueSpeciesConfig.value_id.in_(value_ids)
        )
        result = await session.execute(query)
        return {row.value_id: row for row in result.scalars().all()}

    def _value_to_data(self, value: G2PAttributeValue, schedule=None, species_config=None) -> AttributeValueData:
        return AttributeValueData(
            value_id=value.value_id,
            attribute_id=value.attribute_id,
            value_code=value.value_code,
            value_display=value.value_display,
            parent_value_id=value.parent_value_id,
            interval_days=schedule.interval_days if schedule else None,
            is_active=schedule.is_active if schedule else None,
            notes=schedule.notes if schedule else None,
            requires_ear_tag=species_config.requires_ear_tag if species_config else None,
            is_flock_species=species_config.is_flock_species if species_config else None,''',
    "g2p_attribute_service.py: _value_to_data + species config helpers",
)

# ─── Fix 5: new domain-service extension hook, post_approval_stage, called on
# EVERY approved AWE stage of an intake-form submission's approval chain --
# not just the final one. Without this, a multi-stage policy (e.g. Livestock's
# Kebele -> Woreda -> Zone -> Region hierarchical approval) advances fine
# inside AWE itself, but the registry side has no way to know which stage a
# submission is currently sitting at, since the webhook handler here only
# ever reacted to the 3 TERMINAL_EVENT_TYPES (request_approved/rejected/
# cancelled) and silently ignored every intermediate `stage_completed` event.
# See the livestock extension's g2p_register_domain_service_livestock.py for
# the override that maps stage_order -> LivestockStateEnum.
apply(
    f"{BASE}/services/g2p_register_domain_service.py",
    '''    async def post_intake_upsert(self, rows: list, session: AsyncSession) -> None:
        """Optional extension hook: runs right after an intake-form section's
        records have been upserted (and flushed) into the intake draft table
        -- i.e. when staff click "Next"/save on that section -- well before
        the submission is ever approved or ingested into the live register.
        `rows` are the just-upserted intake-draft ORM rows for that section.
        Override to enrich/mutate those still-draft rows (e.g. reserve an
        identifier ahead of time so it can be shown back to staff
        immediately). No-op by default."""
        pass''',
    '''    async def post_intake_upsert(self, rows: list, session: AsyncSession) -> None:
        """Optional extension hook: runs right after an intake-form section's
        records have been upserted (and flushed) into the intake draft table
        -- i.e. when staff click "Next"/save on that section -- well before
        the submission is ever approved or ingested into the live register.
        `rows` are the just-upserted intake-draft ORM rows for that section.
        Override to enrich/mutate those still-draft rows (e.g. reserve an
        identifier ahead of time so it can be shown back to staff
        immediately). No-op by default."""
        pass

    async def post_approval_stage(
        self, submission, stage_order: int | None, event_type: str, session: AsyncSession
    ) -> None:
        """Optional extension hook: runs once per approved stage of an
        intake-form submission's AWE approval chain -- both for every
        non-final `stage_completed` event (event_type="stage_completed",
        stage_order = the stage that just approved) AND once more for the
        final approval (event_type="request_approved", stage_order = that
        last stage), called BEFORE the submission is marked approved/queued
        for ingest so a field this hook sets on `submission`'s own section
        rows is guaranteed to already be there by the time the async ingest
        worker later copies them into the live register row. A rejected
        stage is never forwarded here -- request_rejected is handled
        separately, unchanged. No-op by default."""
        pass''',
    "g2p_register_domain_service.py: add post_approval_stage hook",
)

apply(
    f"{BASE}/services/g2p_awe_webhook_service.py",
    '''            try:
                if event.event_type in TERMINAL_EVENT_TYPES:
                    await self._apply_terminal_event(event, session)
                log_row.applied = True''',
    '''            try:
                if event.event_type in TERMINAL_EVENT_TYPES:
                    await self._apply_terminal_event(event, session)
                elif event.event_type == "stage_completed":
                    await self._apply_stage_completed_event(event, session)
                log_row.applied = True''',
    "g2p_awe_webhook_service.py: dispatch stage_completed events",
)

apply(
    f"{BASE}/services/g2p_awe_webhook_service.py",
    '''    async def _apply_terminal_event(self, event: AweWebhookEvent, session) -> None:
        if event.artifact_type == REGISTRY_CHANGE_REQUEST_ARTIFACT:
            await self._apply_terminal_event_for_change_request(event, session)
            return
        if event.artifact_type == REGISTRY_INTAKE_FORM_ARTIFACT:
            await self._apply_terminal_event_for_intake_form_submission(event, session)
            return
        raise G2PRegistryException(
            code=G2PRegistryErrorCodes.AWE_WEBHOOK_UNSUPPORTED_ARTIFACT.value[1],
            message=(
                f"{G2PRegistryErrorCodes.AWE_WEBHOOK_UNSUPPORTED_ARTIFACT.value[0]}: "
                f"{event.artifact_type}"
            ),
        )

    async def _apply_terminal_event_for_change_request(''',
    '''    async def _apply_terminal_event(self, event: AweWebhookEvent, session) -> None:
        if event.artifact_type == REGISTRY_CHANGE_REQUEST_ARTIFACT:
            await self._apply_terminal_event_for_change_request(event, session)
            return
        if event.artifact_type == REGISTRY_INTAKE_FORM_ARTIFACT:
            await self._apply_terminal_event_for_intake_form_submission(event, session)
            return
        raise G2PRegistryException(
            code=G2PRegistryErrorCodes.AWE_WEBHOOK_UNSUPPORTED_ARTIFACT.value[1],
            message=(
                f"{G2PRegistryErrorCodes.AWE_WEBHOOK_UNSUPPORTED_ARTIFACT.value[0]}: "
                f"{event.artifact_type}"
            ),
        )

    async def _apply_stage_completed_event(self, event: AweWebhookEvent, session) -> None:
        """Non-terminal per-stage progress on a multi-stage policy (e.g. a
        hierarchical Kebele -> Woreda -> Zone -> Region approval chain) --
        unlike TERMINAL_EVENT_TYPES above, `stage_completed` fires once per
        stage as the request moves through a multi-stage policy, not just
        once at the very end. Only intake-form submissions are handled
        (change requests have no equivalent hook wired up yet). AweWebhookEvent
        carries no explicit per-stage outcome field, so a rejected stage is
        detected the same way engine.py itself distinguishes it: on a
        rejection the whole request's status is already flipped to
        "rejected" by the time this same stage_completed event is emitted
        (see awe/services/engine.py), so status=="rejected" here means this
        stage was a rejection, not an approval -- and request_rejected,
        handled separately by the terminal path above, already covers it.
        Delegates to the resolved domain service's post_approval_stage hook
        (no-op by default), same dispatch-by-register_mnemonic pattern
        save_intake_form_submission_with_session already uses -- silently a
        no-op for any register/domain-service that doesn't implement it.
        """
        if event.artifact_type != REGISTRY_INTAKE_FORM_ARTIFACT:
            return
        if event.status == "rejected":
            return
        if event.stage_order is None:
            return

        submission = await self._resolve_intake_form_submission(event, session)
        intake_service = G2PIntakeFormDataService.get_component()
        register_definition = await intake_service._get_register_definition(
            submission.register_id, session
        )

        import importlib

        domain_factory = getattr(
            importlib.import_module("openg2p_registry_extensions.register_domain.factory"),
            "G2PRegisterDomainFactory",
        ).get_component()
        domain_service = domain_factory.get_domain_service(register_definition.register_mnemonic)
        hook = getattr(domain_service, "post_approval_stage", None) if domain_service else None
        if hook is None:
            return
        await hook(submission, event.stage_order, "stage_completed", session)

    async def _apply_terminal_event_for_change_request(''',
    "g2p_awe_webhook_service.py: add _apply_stage_completed_event",
)

apply(
    f"{BASE}/services/g2p_awe_webhook_service.py",
    '''        submission = await self._resolve_intake_form_submission(event, session)
        intake_service = G2PIntakeFormDataService.get_component()

        if event.event_type == "request_approved":
            await intake_service.approve_submission_with_session(
                submission.submission_id,
                session,
                approved_by=event.actor,
            )
            return''',
    '''        submission = await self._resolve_intake_form_submission(event, session)
        intake_service = G2PIntakeFormDataService.get_component()

        if event.event_type == "request_approved":
            register_definition = await intake_service._get_register_definition(
                submission.register_id, session
            )
            import importlib

            domain_factory = getattr(
                importlib.import_module("openg2p_registry_extensions.register_domain.factory"),
                "G2PRegisterDomainFactory",
            ).get_component()
            domain_service = domain_factory.get_domain_service(register_definition.register_mnemonic)
            hook = getattr(domain_service, "post_approval_stage", None) if domain_service else None
            if hook is not None:
                # Final approval -- runs BEFORE approve_submission_with_session
                # below queues async ingest, so a field the hook sets here is
                # guaranteed to already be on the draft row by the time the
                # celery ingest worker copies it into the live register row
                # (which happens on its own schedule, not synchronously with
                # this webhook call).
                await hook(submission, event.stage_order, "request_approved", session)
            await intake_service.approve_submission_with_session(
                submission.submission_id,
                session,
                approved_by=event.actor,
            )
            return''',
    "g2p_awe_webhook_service.py: call post_approval_stage on final approval",
)

# ─── Fix 7: stamp submission_id onto every row of a section's payload before
# domain validation runs. Without this, validate_domain_attributes only ever
# sees whatever the frontend's dialog-table widget sent — which, for a
# TABLE register like Animal, is built purely from that dialog's configured
# columns, none of which is submission_id. So a row already saved once in
# this same draft resubmits with no submission_id (and no internal_record_id
# either — same gap) on every later save. The livestock extension's
# _validate_no_duplicate_ear_tags relies on submission_id being present to
# recognise "this row already exists in MY OWN draft, don't flag it as
# belonging to a different animal" (see domain_validation_utils.py's
# ear_tag_used_by_other_animal) — without it, revisiting the Livestock
# Details section and clicking Next again (no edits) falsely reports the
# ear tag as already registered to a different animal, blocking Next until
# the tag is changed to something that no longer matches. `submission` is
# already resolved a few lines above (used for existing_rows/upsert right
# after), so this only reads state already in scope — it doesn't change
# what get upserted, only what validate_domain_attributes sees first.
apply(
    f"{BASE}/services/intake_form_data_service.py",
    '''        if domain_service:
            await domain_service.validate_domain_attributes(section_payload or [])''',
    '''        if domain_service:
            for _record in section_payload or []:
                if isinstance(_record, dict):
                    _record.setdefault("submission_id", submission.submission_id)
            await domain_service.validate_domain_attributes(section_payload or [])''',
    "intake_form_data_service.py: stamp submission_id before validate_domain_attributes",
)

# ─── Fix 6: CSRF-exempt the livestock extension's approver-resolver endpoint
# (register_domain/controllers/g2p_approver_resolver_controller.py) — AWE's
# own "http" approver-rule caller (awe/services/resolver.py::_resolve_http)
# is a server-to-server POST with no CSRF cookie/header at all, same as the
# platform's own /awe/webhooks/decision (already in this list, protected by
# its own HMAC signature instead). This file lives in openg2p_registry_
# staff_api, a different installed package from every fix above, so it needs
# its own BASE.
apply(
    "/usr/local/lib/python3.12/site-packages/openg2p_registry_staff_api/main.py",
    '''    "/registrant-auth/callback",
    "/awe/webhooks/decision",
)''',
    '''    "/registrant-auth/callback",
    "/awe/webhooks/decision",
    "/livestock/approver-resolver",
)''',
    "openg2p_registry_staff_api/main.py: CSRF-exempt approver-resolver endpoint",
)

print("ALL PATCHES APPLIED")
