from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st
from persim import wasserstein

from consultas import MASTERS, QUERIES, execute_queries
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


@st.cache_data(max_entries=8)
def sql_results(run_id, selected, _run):
    return execute_queries(_run.payments, _run.master, selected)


def show_sql(run, payments):
    st.subheader("Consultas de auditoría")
    def rule_label(code):
        return f"{code} · {run.rules[code]['name']}"

    rules = sorted(run.rules)
    selected = st.multiselect("Reglas para consultar", rules,
                              default=["A01", "A04", "A05", "A10"], format_func=rule_label)
    query = st.text_input("Buscar ID, proveedor, cuenta o UUID").strip()
    only = st.checkbox("Solo registros con alguna regla seleccionada", True)
    matches = sql_results(run.id, tuple(selected), run)
    payment_rules = [code for code in selected if code not in MASTERS]
    master_rules = [code for code in selected if code in MASTERS]
    suppliers = pd.DataFrame([
        {"ID proveedor": vid, "Proveedor": row["vendor"], "Sitio": row["site"], "Cuenta": row["account"]}
        for vid, row in run.master.items()
    ], columns=["ID proveedor", "Proveedor", "Sitio", "Cuenta"])
    search_cols = ["INVOICE_ID", "VENDOR_ID", "VENDOR_NAME", "BANK_ACCOUNT_NUM", "UUID"]
    pay_tab, master_tab, code_tab = st.tabs(["Pagos", "Maestro de proveedores", "Consultas SQL"])
    with pay_tab:
        show_sql_table(payments, "INVOICE_ID", search_cols, payment_rules, matches,
                       query, only, "Pagos", "consultas_pagos.csv")
    with master_tab:
        st.caption("A05, A16 y A21 identifican proveedores del maestro. A05 muestra cada proveedor de la cuenta compartida.")
        show_sql_table(suppliers, "ID proveedor", ["ID proveedor", "Proveedor", "Cuenta"],
                       master_rules, matches, query, only, "Proveedores", "consultas_maestro.csv")
    with code_tab:
        code = st.selectbox("Ver consulta", rules, format_func=rule_label)
        st.caption("DuckDB ejecuta estas consultas sobre las tablas normalizadas payments y master.")
        st.code(QUERIES[code], language="sql")


def show_sql_table(frame, id_column, search_cols, rules, matches, query, only, label, filename):
    flags = pd.DataFrame({code: frame[id_column].isin(matches[code]) for code in rules}, index=frame.index)
    mask = flags.any(axis=1) if only else pd.Series(True, index=frame.index)
    if query:
        mask &= frame[search_cols].apply(
            lambda col: col.fillna("").str.contains(query, case=False, regex=False)).any(axis=1)
    table = frame.loc[mask].join(flags)
    if rules:
        table["Reglas cumplidas"] = [
            ", ".join(row.index[row]) for _, row in flags.loc[mask].iterrows()
        ]
    st.metric(f"{label} en la selección", len(table))
    st.dataframe(table, hide_index=True)
    download(table, f"Descargar {label.lower()}", filename)


def show_analysis(run, section):
    if section == "Validación de casos":
        validation(run)
        return
    payments, audit_flags, flags = extract(run.id, run)
    st.caption(f"Análisis sobre el extracto completo · {len(payments):,} pagos")
    if section == "Explorador SQL":
        show_sql(run, payments)
    elif payments.empty:
        st.info("La ejecución no contiene pagos.")
    elif section == "Modelos de anomalías":
        show_ml(payments, flags)
    elif section == "Mapper":
        show_mapper(run, payments, audit_flags)
    else:
        show_geometry(run, payments, flags)
