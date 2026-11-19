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

## Áreas de trabajo

Todas las áreas leen la misma ejecución validada. Los filtros del área Auditoría sirven para revisar los hallazgos. Los modelos y la topología utilizan el extracto completo.

| Área | Qué se puede revisar |
| --- | --- |
| Auditoría | Indicadores de pagos únicos, tendencia mensual, categorías, reglas más frecuentes, las 29 reglas, evidencia, exportación y seguimiento de cada caso. |
| Explorador SQL | Las cuatro consultas de Topo sobre proveedores ausentes, discrepancia de cuenta, cuentas compartidas y UUID repetidos. Permite buscar por identificadores, proveedor o cuenta y exportar las filas seleccionadas. |
| Modelos de anomalías | Isolation Forest y LOF con presupuesto de revisión, vecinos y perfil de variables configurables. Incluye solapamiento de modelos, cobertura de señales, variables y rankings descargables. |
| Mapper | Grafo DBSCAN sobre cuatro variables de comportamiento con lente, intervalos y solapamiento ajustables. Permite inspeccionar nodos, aristas y pagos fuera del grafo. |
| Homología persistente | Diagramas de Vietoris–Rips H₀/H₁, distancias de Wasserstein y ranking H₀ por pago. Compara comportamiento frente a comportamiento más las cuatro señales SQL en los mismos pagos. |
| Validación de casos | Resultado esperado y veredicto para cada caso documentado del extracto, con descarga CSV. |

La señal SQL de cuenta compartida se proyecta sobre los pagos de sus proveedores. La regla A05 cuenta el grupo de proveedores en el maestro. Los conteos corresponden a esas unidades distintas. Los casos sembrados son etiquetas parciales, por lo que la evaluación reporta cobertura de casos y coincidencia entre métodos. Los umbrales actuales son parámetros de simulación.

## Referencia y pruebas

La organización en resumen, explorador y metodología sigue la [auditoría topológica de Topo](https://github.com/santirdzrmz/topologia/tree/main/auditoria-topologica), consultada en GitHub en la revisión `6872ba1`. El motor DuckDB, los parámetros, la validación y la persistencia proceden del dashboard descriptivo de este espacio de trabajo.

```sh
python -m unittest discover -s tests
```

Las pruebas comprueban los 30 casos de referencia, los nodos y solapamientos Mapper y la persistencia H₀/H₁ en nubes de puntos conocidas. Los módulos adaptados de Topo conservan su licencia en `LICENSE-Topo`.
