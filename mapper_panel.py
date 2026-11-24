"""Vista de Mapper y trazabilidad de los pagos de cada nodo."""
from collections import defaultdict

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from mapper import build_mapper
from persistence import fit_reference, scaled_behavior


@st.cache_data(max_entries=16)
def case_mapper(payments, lens, intervals, overlap, eps, min_samples):
    features = scaled_behavior(payments, fit_reference(payments))
    return build_mapper(features.to_numpy(), features[lens].to_numpy(),
                        intervals, overlap / 100, eps, min_samples)


def mapper_figure(summary, edges):
    x = summary['Intervalo'].to_numpy()
    groups = summary.groupby('Intervalo')['Nodo']
    y = (groups.cumcount() - (groups.transform('size') - 1) / 2).to_numpy()
    edge_x, edge_y = [], []
    for left, right in edges:
        edge_x.extend((x[left], x[right], None))
        edge_y.extend((y[left], y[right], None))
    fig = go.Figure()
    fig.add_scatter(x=edge_x, y=edge_y, mode='lines',
                    line=dict(color='#8294a7', width=1), hoverinfo='skip')
    counts = summary['Pagos']
    fig.add_scatter(
        x=x, y=y, mode='markers', text=summary['Nodo'],
        customdata=summary[['Pagos', 'Marcados', 'Tasa', 'Diferencia (pp)', 'Límite inferior', 'Límite superior']],
        hovertemplate=('<b>%{text}</b><br>Intervalo %{x}<br>Pagos: %{customdata[0]}'
                       '<br>Marcados: %{customdata[1]} (%{customdata[2]:.1%})'
                       '<br>Frente al periodo: %{customdata[3]:+.2f} pp'
                       '<br>Rango de la lente: [%{customdata[4]:.2f}, %{customdata[5]:.2f}]'
                       '<extra></extra>'),
        marker=dict(size=9 + 27 * np.sqrt(counts / counts.max()),
                    color=summary['Tasa'], colorscale='Teal',
                    cmin=0, cmax=max(0.01, summary['Tasa'].max()),
                    colorbar=dict(title='Pagos marcados', tickformat='.1%'),
                    line=dict(width=1, color='#16324f')),
    )
    fig.update_layout(showlegend=False, xaxis_title='Intervalo de la lente',
                      yaxis=dict(visible=False), margin=dict(l=20, r=20, t=20, b=35))
    fig.update_xaxes(dtick=1, range=[0.5, int(x.max()) + 0.5])
    return fig


def show_mapper(run, payments, flags, scope):
    st.subheader('Mapa de pagos')
    st.write('Cada nodo agrupa pagos de comportamiento similar dentro de un intervalo de la lente. '
             'Dos nodos se conectan si comparten al menos un pago.')
    st.caption('Las cuatro variables de comportamiento se escalan con los pagos del periodo. '
               'Las alertas de auditoría colorean los nodos después de agrupar los pagos.')
    if payments.empty:
        st.info('Se necesitan pagos en el extracto para construir el mapa.')
        return

    lenses = ['Importe log', 'Desviación de importe', 'Días factura a pago',
              'Días factura a vencimiento']
    settings = st.session_state.setdefault('mapper_settings_by_case', {})
    saved_lens, saved_intervals, saved_overlap, saved_eps, saved_min_samples = settings.get(
        scope, (lenses[0], 8, 35, 0.8, 5)
    )
    with st.form(f'mapper_settings_{scope}'):
        lens = st.selectbox('Lente de Mapper', lenses, index=lenses.index(saved_lens))
        a, b = st.columns(2)
        intervals = a.slider('Intervalos de la lente', 2, 20, saved_intervals)
        overlap = b.slider('Solapamiento (%)', 0, 70, saved_overlap, step=5)
        eps = a.slider('Radio de DBSCAN (ε)', 0.1, 4.0, saved_eps, step=0.1)
        min_samples = b.slider('Mínimo de pagos en la vecindad', 2, 30, saved_min_samples)
        submitted = st.form_submit_button('Construir mapa', type='primary', width='stretch', icon=':material/hub:')
    node_key = f'mapper_node_{scope}'
    if submitted:
        settings[scope] = (lens, intervals, overlap, eps, min_samples)
        st.session_state.pop(node_key, None)
    if scope not in settings:
        return

    with st.spinner('Construyendo el grafo de Mapper…'):
        nodes, edges, covered = case_mapper(payments, *settings[scope])

    show_map_results(run, payments, flags, nodes, edges, covered, node_key)


def show_map_results(run, payments, flags, nodes, edges, covered, node_key):
    vendor_findings = defaultdict(set)
    for item in run.findings:
        if not item.payment_ids:
            vendor_findings[item.rule].update(item.vendor_ids)
    context = pd.DataFrame({
        code: payments['VENDOR_ID'].isin(vendor_findings.get(code, ())) for code in flags
    }, index=payments.index)

    controls, overview = st.columns([3, 2])
    with controls:
        rule = st.selectbox('Regla para colorear', [None, *flags.columns],
                            format_func=lambda code: f"{code} · {run.rules[code]['name']}" if code else 'Cualquier regla vinculada al pago')
        by_vendor = rule is not None and (
            st.checkbox('Mostrar hallazgos del maestro como contexto', value=not flags[rule].any(),
                        key=f'{node_key}_context_{rule}')
            if rule in vendor_findings else False
        )
    if by_vendor:
        alert = context[rule].to_numpy()
        st.caption('El color indica pagos de proveedores con un hallazgo de maestro. '
                   'Los proveedores sin pagos se consultan en Auditoría.')
    else:
        alert = (flags[rule] if rule else flags.any(axis=1)).to_numpy()
        st.caption('El color indica pagos vinculados directamente a hallazgos. '
                   'Los pagos del historial de comparación quedan fuera del conteo.')
    baseline = alert.mean()
    overview.metric('Referencia del periodo', f'{baseline:.2%}',
                    help=f'{alert.sum():,} de {len(payments):,} pagos únicos marcados')

    metrics = st.columns(3)
    metrics[0].metric('Nodos', len(nodes))
    metrics[1].metric('Aristas', len(edges))
    metrics[2].metric('Pagos únicos en el grafo', f'{covered.sum():,} / {len(payments):,}')
    node_ids = [f'N{i:02d}' for i in range(1, len(nodes) + 1)]
    if nodes:
        summary = pd.DataFrame(
            [(node_id, interval, len(rows), int(alert[rows].sum()), alert[rows].mean(),
              100 * (alert[rows].mean() - baseline), low, high)
             for node_id, (interval, low, high, rows) in zip(node_ids, nodes)],
            columns=['Nodo', 'Intervalo', 'Pagos', 'Marcados', 'Tasa', 'Diferencia (pp)',
                     'Límite inferior', 'Límite superior'],
        )
        st.plotly_chart(mapper_figure(summary, edges))
        st.caption('El tamaño indica cuántos pagos contiene el nodo. Un pago puede aparecer en varios nodos.')
        with st.expander('Comparar todos los nodos'):
            st.dataframe(summary.style.format({'Tasa': '{:.2%}', 'Diferencia (pp)': '{:+.2f}',
                                               'Límite inferior': '{:.2f}', 'Límite superior': '{:.2f}'}),
                         hide_index=True)
    else:
        st.info('DBSCAN no formó grupos con estos parámetros.')

    st.subheader('Ficha del grupo')
    groups = dict(zip(node_ids, (node[3] for node in nodes)))
    if not covered.all():
        groups['Pagos sin nodo'] = np.flatnonzero(~covered)
    selected = st.selectbox('Grupo de pagos', groups, key=node_key)
    rows = groups[selected]
    group = payments.iloc[rows]
    affected = alert[rows]
    rate = affected.mean()
    cols = st.columns(3)
    cols[0].metric('Pagos en el grupo', len(rows))
    cols[1].metric('Pagos marcados', f'{affected.sum():,} / {len(rows):,}')
    cols[2].metric('Tasa del grupo', f'{rate:.2%}', f'{100 * (rate - baseline):+.2f} pp frente al periodo',
                   delta_color='off')
    if selected == 'Pagos sin nodo':
        st.caption('Pagos que DBSCAN no agrupó con los parámetros seleccionados.')

    show_group_profile(run, group, flags.iloc[rows], context.iloc[rows], affected)
    show_group_findings(run, group, rule)


def rule_codes(flags):
    return flags.apply(lambda row: ', '.join(row.index[row]), axis=1)


def show_group_profile(run, group, direct, context, affected):
    records = [run.payments[key] for key in group['INVOICE_ID']]
    days_to_pay = [(p['paid_on'] - p['invoiced_on']).days for p in records if p['invoiced_on']]
    days_from_due = [(p['paid_on'] - p['due_on']).days for p in records if p['due_on']]
    cols = st.columns(3)
    cols[0].metric('Importe AP mediano', f"{pd.to_numeric(group['IMPORTE_AP']).median():,.2f}")
    cols[1].metric('Días factura a pago · mediana', f'{np.median(days_to_pay):g}' if days_to_pay else '—')
    cols[2].metric('Días desde vencimiento · mediana', f'{np.median(days_from_due):g}' if days_from_due else '—')
    with st.expander('Proveedores, sitios y reglas frecuentes'):
        left, middle, right = st.columns(3)
        with left:
            st.markdown('**Proveedores**')
            st.dataframe((group['VENDOR_NAME'] + ' · ' + group['VENDOR_ID']).value_counts().head(5)
                         .rename_axis('Proveedor').reset_index(name='Pagos'), hide_index=True)
        with middle:
            st.markdown('**Sitios**')
            st.dataframe(group['SITE'].value_counts().head(5).rename_axis('Sitio')
                         .reset_index(name='Pagos'), hide_index=True)
        with right:
            st.markdown('**Reglas vinculadas**')
            counts = direct.sum()
            st.dataframe(counts[counts > 0].nlargest(5).rename_axis('Regla')
                         .reset_index(name='Pagos'), hide_index=True)
        combinations = rule_codes(direct.loc[direct.sum(axis=1) > 1]).value_counts().head(5)
        if not combinations.empty:
            st.markdown('**Coincidencias de reglas en un mismo pago**')
            st.dataframe(combinations.rename_axis('Reglas').reset_index(name='Pagos'), hide_index=True)

    detail = group[['INVOICE_ID', 'VENDOR_ID', 'VENDOR_NAME', 'SITE', 'IMPORTE_AP', 'FECHA_D_PAGO', 'UUID']].copy()
    detail['Marcado según selección'] = affected
    detail['Reglas del pago'] = rule_codes(direct)
    detail['Reglas del maestro · contexto'] = rule_codes(context)
    st.dataframe(detail, hide_index=True)
    st.download_button('Descargar pagos del grupo', detail.to_csv(index=False).encode('utf-8-sig'),
                       'mapper_pagos.csv', 'text/csv', icon=':material/download:')


def show_group_findings(run, group, rule):
    payment_ids = set(group['INVOICE_ID'])
    vendor_ids = set(group['VENDOR_ID'])
    items = {item.id: item for item in run.findings if (rule is None or item.rule == rule) and (
        payment_ids.intersection(item.payment_ids)
        if item.payment_ids else vendor_ids.intersection(item.vendor_ids))}
    with st.expander(f'Evidencia de hallazgos · {len(items):,}'):
        if not items:
            st.caption('Sin hallazgos de la selección para este grupo.')
            return
        selected = st.selectbox('Hallazgo', [None, *items], format_func=lambda key: (
            f"{items[key].rule} · {run.rules[items[key].rule]['name']} · {key[-8:]}"
            if key else 'Selecciona un hallazgo'))
        if selected:
            item = items[selected]
            st.caption('Vinculado a pagos' if item.payment_ids else 'Contexto del maestro')
            st.write(item.evidence)
            if item.payment_ids:
                st.text('ID de pagos del caso: ' + ', '.join(item.payment_ids))
            elif item.vendor_ids:
                st.text('ID de proveedores del caso: ' + ', '.join(item.vendor_ids))
