"""The CRUD module generator.

What matters is not that files appear, but that the generated module is
correct: routes ordered so the catch-all cannot swallow its siblings, one
permission per action, and a migration that makes the module reachable.
"""
import pytest
from scripts.generate_module import (
    FIELD_TYPES,
    ModuleSpec,
    parse_fields,
    render_migration,
    render_model,
    render_router,
    render_schema,
    render_service,
    render_tests,
)


@pytest.fixture
def spec() -> ModuleSpec:
    return ModuleSpec(
        name="Product",
        fields=parse_fields("name:str,price:int,is_active:bool"),
    )


# ---------------------------------------------------------------------------
# Naming
# ---------------------------------------------------------------------------


def test_derives_every_name_from_one_argument():
    s = ModuleSpec(name="Product", fields=[])
    assert s.singular == "product"
    assert s.plural == "products"
    assert s.class_name == "Product"
    assert s.table == "products"
    assert s.route_prefix == "/products"


def test_pluralises_words_ending_in_y():
    """"Categorys" would reach the database and stay there."""
    s = ModuleSpec(name="Category", fields=[])
    assert s.plural == "categories"
    assert s.table == "categories"


def test_accepts_a_multi_word_name():
    s = ModuleSpec(name="PurchaseOrder", fields=[])
    assert s.singular == "purchase_order"
    assert s.plural == "purchase_orders"
    assert s.class_name == "PurchaseOrder"


# ---------------------------------------------------------------------------
# Field parsing
# ---------------------------------------------------------------------------


def test_parses_name_and_type():
    fields = parse_fields("name:str,price:int")
    assert [f.name for f in fields] == ["name", "price"]
    assert fields[0].py_type == "str"
    assert fields[1].py_type == "int"


def test_defaults_to_str_when_no_type_given():
    assert parse_fields("title")[0].py_type == "str"


def test_rejects_an_unknown_type():
    """Generating broken code is worse than refusing."""
    with pytest.raises(ValueError, match="unknown field type"):
        parse_fields("price:money")


def test_rejects_a_field_named_like_a_builtin_column():
    """id/created_at already exist; a duplicate breaks the model."""
    with pytest.raises(ValueError, match="reserved"):
        parse_fields("id:str")


def test_every_declared_type_maps_to_a_column():
    for py_type in FIELD_TYPES:
        field = parse_fields(f"sample:{py_type}")[0]
        assert field.column, f"{py_type} has no SQLAlchemy column"


# ---------------------------------------------------------------------------
# Router: ordering is the trap
# ---------------------------------------------------------------------------


def test_static_routes_come_before_the_catch_all(spec):
    """`/{id}` declared first swallows every sibling route.

    This has already happened twice in this codebase.
    """
    code = render_router(spec)
    list_at = code.index('@router.get("/"')
    detail_at = code.index('@router.get("/{')
    assert list_at < detail_at, "the id route was declared before the list route"


def test_each_endpoint_requires_its_own_action(spec):
    code = render_router(spec)
    for action in ("read", "create", "update", "delete"):
        assert f'require_permission("product.{action}")' in code, action


def test_no_endpoint_is_left_unguarded(spec):
    """An endpoint without a guard is open to any logged-in user."""
    code = render_router(spec)
    decorators = code.count("@router.")
    guards = code.count("require_permission(")
    assert guards == decorators, f"{decorators} endpoints but {guards} guards"


def test_write_endpoints_are_audited(spec):
    code = render_router(spec)
    assert code.count("log_action") >= 3, "create/update/delete must be audited"


def test_audit_calls_match_the_real_signature(spec):
    """log_action takes user_id/action/module/entity_id, and the caller
    commits. An invented signature means every audit row is dropped."""
    code = render_router(spec)
    assert "actor_id=" not in code
    assert "resource_id=" not in code
    assert "user_id=current_user" in code
    assert "module=" in code
    assert "entity_id=" in code
    assert code.count("await db.commit()") >= 3, "audit rows are never committed"


# ---------------------------------------------------------------------------
# Model and schema
# ---------------------------------------------------------------------------


def test_model_declares_every_field(spec):
    code = render_model(spec)
    for name in ("name", "price", "is_active"):
        assert f"{name}: Mapped[" in code, name


def test_model_carries_timestamps_and_a_uuid_key(spec):
    code = render_model(spec)
    assert "TimestampMixin" in code
    assert "primary_key=True" in code
    assert "default=uuid.uuid4" in code


def test_update_schema_makes_every_field_optional(spec):
    """A required field on update forces callers to resend everything."""
    code = render_schema(spec)
    update_block = code[code.index("class UpdateProductRequest") :]
    assert "str | None = None" in update_block
    assert "int | None = None" in update_block


def test_response_schema_reads_from_attributes(spec):
    code = render_schema(spec)
    assert "from_attributes" in code


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------


def test_service_paginates_and_counts(spec):
    code = render_service(spec)
    assert "per_page" in code
    assert "func.count()" in code, "total without a count query is a guess"


def test_service_raises_when_the_row_is_missing(spec):
    code = render_service(spec)
    assert "AppException" in code
    assert "404" in code


# ---------------------------------------------------------------------------
# Migration: the module must be reachable, not just present
# ---------------------------------------------------------------------------


def test_migration_creates_the_table(spec):
    code = render_migration(spec, down_revision="abc123")
    assert 'op.create_table(\n        "products"' in code
    assert 'down_revision: str | None = "abc123"' in code


def test_migration_grants_the_four_permissions(spec):
    code = render_migration(spec, down_revision="abc123")
    for action in ("read", "create", "update", "delete"):
        assert f"product.{action}" in code, action


def test_migration_adds_a_menu_entry(spec):
    """Without it the module exists but nobody can navigate to it.

    Checking only that the string appears is not enough: commenting the
    statement out leaves the text in place while the insert never runs.
    """
    code = render_migration(spec, down_revision="abc123")

    statements = [
        ln.strip() for ln in code.splitlines()
        if "INSERT INTO menus" in ln and not ln.strip().startswith(("#", "--"))
    ]
    assert statements, "no live INSERT INTO menus statement"
    assert not any("--" in s.split("INSERT")[0] for s in statements), (
        "the menu insert is commented out"
    )
    assert "product.read" in code, "menu must be bound to the read permission"


def test_migration_is_reversible(spec):
    code = render_migration(spec, down_revision="abc123")
    assert "def downgrade()" in code
    assert "drop_table" in code


def test_migration_can_run_twice(spec):
    """Re-running a half-applied migration must not explode."""
    code = render_migration(spec, down_revision="abc123")
    assert "WHERE NOT EXISTS" in code or "ON CONFLICT" in code


def test_generated_tests_import_only_what_they_use(spec):
    """Unused imports fail ruff, so generated code would break CI."""
    code = render_tests(spec)
    import_line = next(
        ln for ln in code.splitlines() if ln.startswith("from app.models.rbac")
    )
    for name in ("Permission", "RolePermission"):
        assert name in import_line
    assert "Role," not in import_line, "Role is imported but never used"


def test_generated_tests_send_the_csrf_token(spec):
    """Write requests are rejected without it, so the tests would fail."""
    code = render_tests(spec)
    assert "X-CSRF-Token" in code


# ---------------------------------------------------------------------------
# Generated tests
# ---------------------------------------------------------------------------


def test_generated_tests_cover_the_permission_guard(spec):
    code = render_tests(spec)
    assert "403" in code, "generated tests never prove the guard works"


def test_generated_tests_cover_every_endpoint(spec):
    code = render_tests(spec)
    for verb in ("get", "post", "put", "delete"):
        assert f"async_client.{verb}(" in code, verb
