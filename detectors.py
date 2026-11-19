import sqlite3
import pandas as pd

RULES = {
    'A': ('Proveedor no registrado', "SELECT p.fila FROM pagos p WHERE p.proveedor <> '' AND NOT EXISTS (SELECT 1 FROM maestro m WHERE m.proveedor=p.proveedor)"),
    'B': ('Cuenta fuera del maestro', "SELECT p.fila FROM pagos p WHERE p.cuenta <> '' AND EXISTS (SELECT 1 FROM maestro m WHERE m.proveedor=p.proveedor) AND NOT EXISTS (SELECT 1 FROM maestro m WHERE m.proveedor=p.proveedor AND m.cuenta=p.cuenta)"),
    'C': ('Cuenta compartida', "SELECT p.fila FROM pagos p WHERE p.proveedor IN (SELECT m.proveedor FROM maestro m JOIN (SELECT cuenta FROM maestro WHERE cuenta <> '' GROUP BY cuenta HAVING COUNT(DISTINCT proveedor)>1) c ON m.cuenta=c.cuenta)"),
    'D': ('UUID repetido', "SELECT p.fila FROM pagos p JOIN (SELECT uuid FROM pagos WHERE uuid <> '' GROUP BY uuid HAVING COUNT(*)>1) d ON p.uuid=d.uuid"),
}

def detect(payments, master):
    def clean(series):
        return series.str.strip()
    p = pd.DataFrame({'fila': range(len(payments)), 'proveedor': clean(payments['VENDOR_ID']),
                      'cuenta': clean(payments['BANK_ACCOUNT_NUM']), 'uuid': clean(payments['UUID']).str.upper()})
    m = pd.DataFrame({'proveedor': clean(master['Id Proveedor']), 'cuenta': clean(master['Cuenta'])})
    result = pd.DataFrame(False, index=range(len(payments)), columns=list(RULES))
    with sqlite3.connect(':memory:') as connection:
        p.to_sql('pagos', connection, index=False)
        m.to_sql('maestro', connection, index=False)
        connection.execute('CREATE INDEX idx_master ON maestro(proveedor, cuenta)')
        for factor, (_, sql) in RULES.items():
            rows = pd.read_sql_query(sql, connection)['fila']
            result.loc[rows, factor] = True
    return result

