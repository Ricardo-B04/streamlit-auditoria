"""Panel local de auditoría de pagos."""
from collections import Counter
from pathlib import Path
import sqlite3

import pandas as pd
import streamlit as st

from auditoria import money
from reporte import report, vendor_options
from seguimiento import AuditStore, ConflictError, DEFAULT_CASE, STATES
from validacion import DataValidationError

st.set_page_config(page_title="Auditoría de pagos", layout="wide")


@st.cache_resource
def get_store():
    return AuditStore(Path(__file__).parent / "datos" / "seguimiento.sqlite3")


FILTERS = ("periodo", "sitio", "proveedor", "categoria", "regla", "severidad", "estado", "responsable")
COLUMNS = {
    "rule": "Regla", "date": "Fecha", "severity": "Severidad", "site": "Sitio",
    "vendor": "Proveedor", "amount": "Importe afectado", "status": "Estado",
    "owner": "Responsable", "evidence": "Evidencia",
}


def clear_filters():
    for key in FILTERS:
        st.session_state.pop(key, None)


def payment_table(run, ids):
    rows = [run.payments[key] for key in ids]
    st.dataframe([{
        "ID de factura": p["id"], "Proveedor": p["vendor"], "Sitio": p["site"],
        "Fecha de pago": p["paid_on"], "Vencimiento": p["due_on"], "Pagado": money(p["paid"]),
    } for p in rows], hide_index=True)


def follow_up(store, run, item, case):
    with st.form(f"seguimiento-{item.id}-{case['revision']}"):
        owner = st.text_input("Responsable", value=case["owner"], max_chars=120)
        status = st.selectbox("Estado del caso", STATES, index=STATES.index(case["status"]))
        resolution = st.text_area("Resolución", value=case["resolution"], max_chars=4000)
        if st.form_submit_button("Guardar seguimiento"):
            try:
                store.save_case(run.id, item.id, owner, status, resolution, case["revision"])
            except ConflictError as error:
                st.warning(str(error))
            except (ValueError, sqlite3.Error) as error:
                st.error(str(error))
            else:
                st.session_state["mensaje"] = f"Seguimiento guardado para {item.rule}."
                st.rerun()

    with st.expander("Historial de seguimiento"):
        events = store.history(item.id)
        if events:
            st.dataframe([{
                "Fecha UTC": x["updated_at"], "Estado": x["status"],
                "Responsable": x["owner"], "Resolución": x["resolution"],
            } for x in events], hide_index=True)
        else:
            st.caption("Sin cambios registrados.")


def show_detail(store, run, item, cases, vendors):
    rule = run.rules[item.rule]
    st.subheader(f"{item.rule} · {rule['name']}")
    st.text(rule["criterion"])
    st.caption(rule["risk"])
    st.info(item.evidence)
    if item.payment_ids:
        st.markdown("**Pagos del caso**")
        payment_table(run, item.payment_ids)
    else:
        st.dataframe([
            {"Proveedor": vendors[key], "Sitio": run.master[key]["site"]}
            for key in item.vendor_ids
        ], hide_index=True)
    if item.context_ids:
        with st.expander(f"Historial de comparación · {len(item.context_ids)} pagos"):
            payment_table(run, item.context_ids)
    follow_up(store, run, item, cases.get(item.id, DEFAULT_CASE))


def main():
    store = get_store()
    st.title("Auditoría de pagos")
    refresh = st.sidebar.button("Actualizar datos")
    if refresh or "run_id" not in st.session_state:
        try:
            run = store.refresh()
            if run.id != st.session_state.get("run_id"):
                clear_filters()
            st.session_state["run_id"] = run.id
        except (OSError, sqlite3.Error, DataValidationError) as error:
            st.error(f"Error al cargar el extracto. {error}")
    if "run_id" not in st.session_state:
        st.stop()
    run = store.get_run(st.session_state["run_id"])
    message = st.session_state.pop("mensaje", None)
    if message:
        st.success(message)
    st.caption(f"Datos simulados · Corte {run.end or 'sin pagos'} · {len(run.rules)} reglas · Ejecución {run.id[:12]}")
    vendors = vendor_options(run)
    cases = store.cases()
    sites = sorted({r["site"] for r in (*run.payments.values(), *run.master.values())} - {""})
    categories = sorted({r["category"] for r in run.rules.values()})
    severities = sorted({r["severity"] for r in run.rules.values()})

    with st.sidebar:
        st.header("Filtros")
        st.button("Limpiar filtros", on_click=clear_filters)
        period = st.date_input("Periodo de pago", (run.start, run.end), min_value=run.start,
                               max_value=run.end, key="periodo") if run.start else ()
        site = st.selectbox("Sitio", [None, *sites], format_func=lambda x: x or "Todos", key="sitio")
        vendor = st.selectbox("Proveedor", [None, *sorted(vendors, key=vendors.get)],
                              format_func=lambda x: vendors.get(x, "Todos"), key="proveedor")
        category = st.selectbox("Categoría", [None, *categories], format_func=lambda x: x or "Todas", key="categoria")
        rule = st.selectbox("Regla", [None, *sorted(run.rules)], key="regla",
                            format_func=lambda x: f"{x} · {run.rules[x]['name']}" if x else "Todas")
        severity = st.selectbox("Severidad", [None, *severities], format_func=lambda x: x or "Todas", key="severidad")
        status = st.selectbox("Estado", [None, *STATES], format_func=lambda x: x or "Todos", key="estado")
        owner = st.text_input("Responsable", key="responsable")

    if run.start and len(period) != 2:
        st.info("Selecciona el inicio y el fin del periodo.")
        st.stop()
    dates = [day.isoformat() for day in period] or [None, None]
    rows, monthly, counts, payments, affected, suppliers, total = report(
        run, cases, *dates, site, vendor, severity, rule, category, status, owner
    )
    labels = {
        "Pagos revisados": f"{payments:,}", "Alertas": f"{len(rows):,}",
        "Pagos afectados": f"{affected:,}", "Proveedores afectados": f"{suppliers:,}",
        "Importe afectado": money(total), "Tasa de afectación": f"{affected / payments:.1%}" if payments else "—",
    }
    for col, (label, value) in zip(st.columns(len(labels)), labels.items()):
        col.metric(label, value, border=True)
    st.caption("Importes en unidades del extracto. Cada pago afectado aporta una sola vez al total.")

    overview, explorer, catalog = st.tabs(["Resumen", "Explorar alertas", "Matriz de reglas"])
    with overview:
        left, right = st.columns([3, 2])
        with left:
            st.subheader("Alertas por mes")
            if run.start:
                months = pd.period_range(dates[0], dates[1], freq="M")
                st.line_chart(pd.Series(
                    [monthly.get(month.start_time.date(), 0) for month in months],
                    index=months.to_timestamp(), name="Alertas"), color="#137C72")
            else:
                st.caption("Sin pagos en el extracto.")
        with right:
            st.subheader("Alertas por categoría")
            category_counts = {k: v for k, v in counts.items() if category is None or k == category}
            st.bar_chart(pd.Series(category_counts, name="Alertas"), horizontal=True, color="#3982AA")

    with explorer:
        if not rows:
            st.info("No hay alertas con los filtros seleccionados.")
        else:
            order = st.selectbox("Ordenar por", ["Fecha", "Importe", "Severidad"])
            severity_rank = {"Crítica": 4, "Alta": 3, "Media/Alta": 2, "Media": 1}
            order_key = {"Fecha": lambda r: r["date"], "Importe": lambda r: r["amount"],
                         "Severidad": lambda r: severity_rank.get(r["severity"], 0)}[order]
            rows.sort(key=lambda r: (order_key(r), r["id"]), reverse=True)
            page = st.number_input("Página", min_value=1, max_value=(len(rows) + 24) // 25, step=1)
            page_rows = rows[(page - 1) * 25:page * 25]
            index = {r["id"]: r for r in page_rows}
            st.dataframe([{label: money(r[key]) if key == "amount" else r[key]
                           for key, label in COLUMNS.items()} for r in page_rows], hide_index=True)
            selected = st.selectbox("Alerta para revisar", [None, *index], format_func=lambda key: (
                f"{index[key]['rule']} · {index[key]['date'] or 'Sin fecha'} · "
                f"{index[key]['vendor']} · {key[-8:]}" if key else "Selecciona una alerta de esta página"
            ))
            if selected:
                item = next(item for item in run.findings if item.id == selected)
                show_detail(store, run, item, cases, vendors)
    with catalog:
        count_by_rule = Counter(r["rule"] for r in rows)
        st.dataframe([{
            "ID": key, "Alerta": r["name"], "Categoría": r["category"], "Severidad": r["severity"],
            "Coincidencias visibles": count_by_rule[key], "Regla funcional": r["criterion"],
        } for key, r in sorted(run.rules.items())], hide_index=True)
        with st.expander("Parámetros de esta ejecución"):
            st.json(run.metadata["parameters"], expanded=False)


main()
