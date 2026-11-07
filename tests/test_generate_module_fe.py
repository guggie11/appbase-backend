"""The frontend half of the module generator.

A page that compiles is not enough: the action buttons must be gated by the
same permissions the backend enforces, and deletes must ask first. Those are
the parts that are easy to leave out when copying a page by hand.
"""
import pytest
from scripts.generate_module import (
    ModuleSpec,
    parse_fields,
    render_fe_modal,
    render_fe_page,
    render_fe_queries,
    render_fe_types,
)


@pytest.fixture
def spec() -> ModuleSpec:
    return ModuleSpec(
        name="Product",
        fields=parse_fields("name:str,price:int,note:text,is_active:bool"),
    )


# ---------------------------------------------------------------------------
# Queries
# ---------------------------------------------------------------------------


def test_queries_cover_the_four_operations(spec):
    code = render_fe_queries(spec)
    for hook in ("useProducts", "useCreateProduct", "useUpdateProduct", "useDeleteProduct"):
        assert f"export function {hook}" in code, hook


def test_mutations_invalidate_the_list(spec):
    """Without it the table still shows stale rows after a write."""
    code = render_fe_queries(spec)
    assert code.count("invalidateQueries") >= 3


def test_mutations_await_the_refetch(spec):
    """Returning the invalidation makes the mutation settle after the
    refetch, so the table never shows a row that is already deleted."""
    code = render_fe_queries(spec)
    assert code.count("return qc.invalidateQueries") >= 3, (
        "invalidation is fired but not awaited"
    )


def test_queries_hit_the_backend_route(spec):
    code = render_fe_queries(spec)
    assert "'/products" in code or '"/products' in code


def test_list_query_passes_pagination(spec):
    code = render_fe_queries(spec)
    assert "page" in code and "per_page" in code


# ---------------------------------------------------------------------------
# Page: permission gating is the point
# ---------------------------------------------------------------------------


def test_create_button_is_gated(spec):
    """Showing a button the backend will refuse is a lie to the user."""
    code = render_fe_page(spec)
    assert "product.create" in code


def test_edit_and_delete_are_gated(spec):
    code = render_fe_page(spec)
    assert "product.update" in code
    assert "product.delete" in code


def test_page_uses_the_permission_hook(spec):
    code = render_fe_page(spec)
    assert "usePermission" in code


def test_delete_asks_for_confirmation(spec):
    """A one-click irreversible delete in a table is a trap."""
    code = render_fe_page(spec)
    assert "DeleteConfirmDialog" in code


def test_page_renders_every_field_as_a_column(spec):
    code = render_fe_page(spec)
    for name in ("name", "price", "note", "is_active"):
        assert f"'{name}'" in code or f'"{name}"' in code, name


def test_page_has_a_heading(spec):
    """A standalone page with only a subtitle has no anchor for the eye."""
    code = render_fe_page(spec)
    assert "<h1" in code


def test_heading_is_plural(spec):
    """A list page titled "Product" contradicts everything around it."""
    code = render_fe_page(spec)
    heading = code[code.index("<h1") : code.index("</h1>")]
    assert "Products" in heading, heading


def test_empty_state_is_plural(spec):
    """"No product yet" reads as a typo; the list holds many."""
    code = render_fe_page(spec)
    assert "No products yet" in code


def test_boolean_column_drops_the_is_prefix(spec):
    """"IS ACTIVE" is a column name leaking into the chrome."""
    code = render_fe_page(spec)
    assert "'Active'" in code, "is_active should read as Active"
    assert "'Is active'" not in code


def test_page_reads_pagination_from_meta(spec):
    """PaginatedResponse nests page/total under .meta, not at the top."""
    code = render_fe_page(spec)
    assert "data?.meta" in code, "pagination read from the wrong level"


def test_page_imports_the_dialog_from_where_it_lives(spec):
    """DeleteConfirmDialog is not exported from shared/ui."""
    code = render_fe_page(spec)
    assert "pages/users/components/DeleteConfirmDialog" in code


def test_page_reuses_the_shared_table(spec):
    """A bespoke table would drift from the rest of the app."""
    code = render_fe_page(spec)
    assert "DataTable" in code


# ---------------------------------------------------------------------------
# Modal: field types must reach the right input
# ---------------------------------------------------------------------------


def test_bool_becomes_a_labelled_checkbox(spec):
    """A boolean in a text box is nonsense, and an unlabelled box is worse."""
    code = render_fe_modal(spec)
    assert 'type="checkbox"' in code
    block = code[code.index('type="checkbox"') - 200 : code.index('type="checkbox"') + 300]
    assert "Active" in block, "the checkbox has no visible label"


def test_int_becomes_a_number_input(spec):
    code = render_fe_modal(spec)
    assert 'type="number"' in code


def test_text_becomes_a_textarea(spec):
    """A long note in a single-line input is unusable."""
    code = render_fe_modal(spec)
    assert "<textarea" in code


def test_modal_validates_before_submitting(spec):
    code = render_fe_modal(spec)
    assert "zod" in code or "z.object" in code


def test_modal_handles_both_create_and_edit(spec):
    code = render_fe_modal(spec)
    assert "Create" in code and "Edit" in code


# ---------------------------------------------------------------------------
# Route
# ---------------------------------------------------------------------------


def test_route_is_permission_guarded(spec):
    """An unguarded route lets anyone open the page directly by URL."""
    from scripts.generate_module import render_fe_route

    code = render_fe_route(spec)
    assert "PermissionRoute" in code
    assert 'permission="product.read"' in code


def test_route_wraps_the_page_in_the_layout(spec):
    """Without it the page renders with no sidebar or top bar."""
    from scripts.generate_module import render_fe_route

    assert "WithLayout" in render_fe_route(spec)


# ---------------------------------------------------------------------------
# Types
# ---------------------------------------------------------------------------


def test_type_declares_every_field(spec):
    code = render_fe_types(spec)
    assert "export interface Product" in code
    assert "name: string" in code
    assert "price: number" in code
    assert "is_active: boolean" in code


def test_type_includes_server_fields(spec):
    code = render_fe_types(spec)
    for field in ("id", "created_at", "updated_at"):
        assert field in code, field
