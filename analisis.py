from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st
from persim import wasserstein

from detectors import RULES, detect
from mapper_panel import show_mapper
from ml import MODELS, PROFILES, run_ml
from persistence import diagrams, fit_reference, mass_scores, point_cloud, scaled_behavior


@st.cache_data(max_entries=2)
def extract(run_id, _run):
    columns = {"id": "INVOICE_ID", "vendor_id": "VENDOR_ID", "vendor": "VENDOR_NAME",
               "uuid": "UUID", "site": "SITE", "account": "BANK_ACCOUNT_NUM", "ap": "IMPORTE_AP",
               "paid_on": "FECHA_D_PAGO", "invoiced_on": "FECHA_FACTURA", "due_on": "FECHA_VENCIMIENTO"}
    payments = pd.DataFrame(_run.payments.values(), columns=list(columns)).rename(columns=columns)
    for col in ("FECHA_D_PAGO", "FECHA_FACTURA", "FECHA_VENCIMIENTO"):
        payments[col] = pd.to_datetime(payments[col]).dt.strftime("%d/%m/%y")
    payments = payments.fillna("").astype(str)
    flags = pd.DataFrame(False, index=payments.INVOICE_ID, columns=sorted(_run.rules))
    for item in _run.findings:
        if item.payment_ids:
            flags.loc[list(item.payment_ids), item.rule] = True
    master = pd.DataFrame([(key, row["account"] or "") for key, row in _run.master.items()],
                          columns=["Id Proveedor", "Cuenta"])
    return payments, flags.reset_index(drop=True), detect(payments, master)


def download(frame, label, filename):
    st.download_button(label, frame.to_csv(index=False).encode("utf-8-sig"), filename, "text/csv")


@st.cache_data(max_entries=6)
def models(payments, flags, profile, budget, neighbors):
    return {name: run_ml(payments, flags, name, profile, budget, neighbors) for name in MODELS}


def show_ml(payments, flags):
    st.subheader("Priorización de pagos")
    st.caption("El presupuesto fija la proporción de pagos a revisar. El perfil enriquecido incluye las cuatro señales SQL de Topo, la frecuencia de UUID y el número de proveedores por cuenta.")
    st.write("Isolation Forest identifica pagos fáciles de aislar. LOF compara la densidad de cada pago con la de sus vecinos.")
    if len(payments) < 3:
        st.info("Se requieren al menos tres pagos.")
        return
    with st.form("modelos"):
        profile = st.selectbox("Variables del modelo", PROFILES)
        budget = st.slider("Presupuesto de revisión (%)", 1, 100, 10)
        neighbors = st.number_input("Vecinos de LOF", 1, len(payments)-1, min(35, len(payments)-1))
        st.form_submit_button("Aplicar configuración")
    results = models(payments, flags, profile, budget, neighbors)
    summary = []
    for name, (scores, _, elapsed) in results.items():
        alerts = scores["Alerta ML"]
        summary.append({"Modelo": name, "Priorizados": int(alerts.sum()),
                        "Con alerta de reglas": int((alerts & flags.any(axis=1)).sum()),
                        "Tiempo (s)": round(elapsed, 2)})
    st.dataframe(summary, hide_index=True)
    priorities = {name: scores["Alerta ML"] for name, (scores, _, _) in results.items()}
    agreement = int((priorities["Isolation Forest"] & priorities["LOF"]).sum())
    st.caption(f"Ambos modelos coinciden en priorizar {agreement:,} pagos.")
    with st.expander("Cobertura de señales SQL por modelo"):
        coverage = []
        for key, (label, _) in RULES.items():
            mask = flags[key]
            coverage.append({"Señal SQL": label, "Pagos con señal": int(mask.sum()),
                             **{model: int((mask & chosen).sum()) for model, chosen in priorities.items()}})
        st.dataframe(coverage, hide_index=True)
    name = st.radio("Ranking", MODELS, horizontal=True)
    scores, variables, _ = results[name]
    table = pd.concat([payments, scores], axis=1)
    table["Señales SQL de Topo"] = flags.apply(lambda row: ", ".join(row.index[row]), axis=1)
    if st.checkbox("Solo pagos priorizados", True):
        table = table[table["Alerta ML"]]
    table = table.sort_values("Puntuación", ascending=False, kind="stable")
    st.dataframe(table, hide_index=True)
    download(table, "Descargar ranking ML", "ranking_ml.csv")
    with st.expander("Variables utilizadas"):
        st.dataframe(variables)


@st.cache_data(max_entries=2)
def geometry(payments, flags):
    reference = fit_reference(payments)
    points = point_cloud(payments, flags, reference)
    return mass_scores(points), diagrams(points), diagrams(scaled_behavior(payments, reference).to_numpy())


def show_geometry(run, payments, flags):
    st.subheader("Homología persistente")
    st.write("Compara los mismos pagos en dos representaciones. Una usa cuatro variables de comportamiento. La otra añade las cuatro señales SQL de Topo con peso 4.")
    st.caption("H₀ describe componentes y H₁ ciclos. Los diagramas usan hasta 600 pagos representativos. El ranking H₀ usa todos los pagos y mide la distancia necesaria para alcanzar una componente con el 25 % del extracto.")
    if st.button("Calcular homología persistente"):
        st.session_state["geometria"] = run.id
    if st.session_state.get("geometria") != run.id:
        return
    scores, enriched, baseline = geometry(payments, flags)
    for dim, col in enumerate(st.columns(2)):
        col.metric(f"Distancia de Wasserstein H{dim}", f"{wasserstein(enriched[dim], baseline[dim]):.3f}")
    intervals = pd.DataFrame([(name, f"H{dim}", x, y) for name, dgms in [
        ("Comportamiento", baseline), ("Comportamiento + reglas", enriched)]
        for dim, dgm in enumerate(dgms) for x, y in dgm],
        columns=["Representación", "Dimensión", "Nacimiento", "Muerte"])
    if not intervals.empty:
        chart = px.scatter(intervals, x="Nacimiento", y="Muerte", color="Representación", facet_col="Dimensión")
        limit = intervals.Muerte.max()
        chart.add_shape(type="line", x0=0, y0=0, x1=limit, y1=limit, line_dash="dot", row="all", col="all")
        st.plotly_chart(chart)
        download(intervals, "Descargar intervalos", "persistencia.csv")
    ranking = payments.assign(Puntaje_H0=scores, Alerta=flags.any(axis=1)).sort_values("Puntaje_H0", ascending=False, kind="stable")
    st.dataframe(ranking, hide_index=True)
    download(ranking, "Descargar ranking H₀", "ranking_h0.csv")


def validation(run):
    cases = pd.read_csv(Path(__file__).parent/"datos"/"casos_esperados.csv")
    verdicts = []
    for row in cases.itertuples():
        items = [item for item in run.findings if item.rule == row.ID]
        keys = [k.strip() for k in row.Registros.split(",")]
        expected = set(keys)
        if row.ID in {"A06", "A07", "A08"}:
            flagged = {k for item in items for k in item.payment_ids}
            ok = keys[0] not in flagged and keys[1] in flagged
        elif row.ID in {"A05", "A16", "A20", "A21"}:
            ok = any(expected == set(item.vendor_ids) for item in items)
        elif row.ID == "A24":
            ok = any(item.site == keys[0] and item.occurred_on.strftime("%Y-%m") == keys[1] for item in items)
        elif row.ID in {"A19", "A23", "A28", "A29"}:
            ok = any(keys[-1] in item.payment_ids and expected <= set(item.payment_ids + item.context_ids) for item in items)
        else:
            ok = any(expected == set(item.payment_ids) for item in items)
        verdicts.append(ok)
    cases["Verificado"] = verdicts
    st.metric("Casos de referencia detectados", f"{sum(verdicts)} / {len(cases)}")
    st.caption("La cobertura se calcula sobre los casos documentados. Las etiquetas parciales permiten verificar ejemplos concretos de las reglas.")
    st.dataframe(cases, hide_index=True)
    download(cases, "Descargar validación", "validacion.csv")


def show_analysis(run, section):
    if section == "Validación de casos":
        validation(run)
        return
    payments, audit_flags, flags = extract(run.id, run)
    st.caption(f"Análisis sobre el extracto completo · {len(payments):,} pagos")
    if payments.empty:
        st.info("La ejecución no contiene pagos.")
    elif section == "Explorador SQL":
        st.subheader("Conciliación de pagos")
        selected = st.multiselect("Señales SQL de Topo", list(RULES), default=list(RULES),
                                  format_func=lambda key: RULES[key][0])
        only = st.checkbox("Solo pagos con alguna señal seleccionada", True)
        query = st.text_input("Buscar ID, proveedor, cuenta o UUID").strip()
        matching = flags[selected].any(axis=1) if only else pd.Series(True, index=payments.index)
        if query:
            fields = payments[["INVOICE_ID", "VENDOR_ID", "VENDOR_NAME", "BANK_ACCOUNT_NUM", "UUID"]]
            matching &= fields.apply(lambda col: col.str.contains(query, case=False, regex=False)).any(axis=1)
        table = payments[matching].join(flags.rename(columns={k: v[0] for k, v in RULES.items()}))
        table["Reglas de auditoría vinculadas al pago"] = [
            ", ".join(row.index[row]) for _, row in audit_flags[matching].iterrows()]
        st.metric("Pagos en la selección", len(table))
        st.dataframe(table, hide_index=True)
        download(table, "Descargar pagos seleccionados", "conciliacion.csv")
        with st.expander("Consultas SQL"):
            for label, sql in RULES.values():
                st.markdown(f"**{label}**")
                st.code(sql, language="sql")
    elif section == "Modelos de anomalías":
        show_ml(payments, flags)
    elif section == "Mapper":
        show_mapper(run.id, payments, flags)
    else:
        show_geometry(run, payments, flags)
