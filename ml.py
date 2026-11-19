"""Detección transductiva: ajustar y puntuar cada escenario sin etiquetas."""
import math
import time
import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from sklearn.neighbors import LocalOutlierFactor
from sklearn.preprocessing import RobustScaler



MODELS = ['Isolation Forest', 'LOF']
PROFILES = ['Comportamiento', 'Comportamiento + auditoría']

def features(payments, flags, profile):
    if profile not in PROFILES:
        raise ValueError('Perfil desconocido')
    p = payments.reset_index(drop=True)
    vendor = p['VENDOR_ID'].str.strip()
    amount = pd.to_numeric(p['IMPORTE_AP'].str.replace(',', '', regex=False), errors='coerce')
    date = pd.to_datetime(p['FECHA_D_PAGO'], format='%d/%m/%y', errors='coerce')
    invoice = pd.to_datetime(p['FECHA_FACTURA'], format='%d/%m/%y', errors='coerce')
    due = pd.to_datetime(p['FECHA_VENCIMIENTO'], format='%d/%m/%y', errors='coerce')
    median = amount.groupby(vendor).transform('median')
    x = pd.DataFrame({
        'Importe log': np.sign(amount) * np.log1p(amount.abs()),
        'Desviación de importe': (amount - median) / (median.abs() + 1),
        'Pagos del proveedor': vendor.map(vendor.value_counts()),
        'Días factura a pago': (date - invoice).dt.days,
        'Días desde vencimiento': (date - due).dt.days,
        'Día de semana': date.dt.dayofweek,
        'Día del mes': date.dt.day,
    })
    if profile == PROFILES[1]:
        # Señales explícitas de negocio: no son etiquetas, pero codifican las reglas SQL.
        for key in flags:
            x[f'Regla {key}'] = flags[key].astype(int)
        account = p['BANK_ACCOUNT_NUM'].str.strip().replace('', np.nan)
        uuid = p['UUID'].str.strip().str.upper().replace('', np.nan)
        x['Frecuencia UUID'] = uuid.map(uuid.value_counts()).fillna(0)
        x['Proveedores por cuenta de pago'] = account.map(pd.DataFrame({'a':account,'v':vendor}).groupby('a').v.nunique()).fillna(0)
    return x.replace([np.inf, -np.inf], np.nan)

def run_ml(payments, flags, model, profile, budget=10, neighbors=35):
    if model not in MODELS or not 0 < budget <= 100 or len(payments) < 3:
        raise ValueError('Modelo, presupuesto o tamaño de muestra inválido')
    start = time.perf_counter()
    x = features(payments, flags, profile)
    # Medianas y escala se estiman dentro del escenario, nunca a partir de etiquetas.
    filled = x.fillna(x.median()).fillna(0)
    scaled = RobustScaler().fit_transform(filled)
    if model == MODELS[0]:
        estimator = IsolationForest(n_estimators=150, random_state=42, n_jobs=1)
        estimator.fit(scaled)
        scores = -estimator.score_samples(scaled)
    else:
        estimator = LocalOutlierFactor(n_neighbors=min(neighbors, len(x)-1), n_jobs=1)
        estimator.fit_predict(scaled)
        scores = -estimator.negative_outlier_factor_
    k = max(1, math.ceil(len(x) * budget / 100))
    order = np.argsort(-scores, kind='stable')
    alerts = np.zeros(len(x), dtype=bool)
    alerts[order[:k]] = True
    result = pd.DataFrame({'Puntuación': scores, 'Alerta ML': alerts}, index=x.index)
    return result, x, time.perf_counter()-start

