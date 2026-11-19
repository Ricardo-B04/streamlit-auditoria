# Dashboard de auditoría en Streamlit

Panel descriptivo para examinar los pagos y el maestro de proveedores simulados. Evalúa las 29 reglas de la matriz sobre el historial completo y muestra los hallazgos, la evidencia y el seguimiento.

## Ejecutar localmente

Con Python 3.12 o 3.13, desde esta carpeta:

```sh
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m streamlit run app.py --server.address 127.0.0.1
```

Abre [el dashboard local](http://127.0.0.1:8501). Usa los filtros laterales, selecciona una alerta en **Explorar alertas** y consulta los pagos del caso y su historial de comparación. Desde el detalle puedes asignar responsable, actualizar el estado y registrar una resolución. **Actualizar datos** valida y vuelve a evaluar los CSV de `datos/`. La base local de seguimiento se crea en esta carpeta.

Los indicadores de pagos e importe afectados cuentan cada pago una vez. El historial de comparación aparece en el detalle. Los importes están en unidades del extracto. Los parámetros de prueba se consultan en **Matriz de reglas**.

## Referencia y pruebas

La organización en resumen, explorador y metodología sigue la [auditoría topológica de Topo](https://github.com/santirdzrmz/topologia/tree/main/auditoria-topologica), consultada en el checkout local `6872ba1`. El motor DuckDB, los parámetros, la validación y la persistencia proceden del dashboard descriptivo de este espacio de trabajo.

```sh
python -m unittest discover -s tests
```

La prueba comprueba los 30 casos de referencia, incluidos los dos de A21.
