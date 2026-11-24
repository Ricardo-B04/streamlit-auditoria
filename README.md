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

## Despliegue en Railway

El `Dockerfile` usa Python 3.12 y el puerto asignado por Railway. `railway.json` comprueba la salud de Streamlit antes de activar el despliegue.

Adjunta un volumen en `/data` y configura `AUDIT_DB_PATH=/data/seguimiento.sqlite3` para conservar el seguimiento entre reinicios y despliegues. Mantén una sola réplica al utilizar SQLite. Los CSV simulados se distribuyen con el código. La base local no se sube: el seguimiento en la nube comienza vacío.

La aplicación no incorpora inicio de sesión: cualquier persona con acceso a la URL puede consultar los datos simulados y modificar el seguimiento. Antes de utilizar datos reales, configura autenticación y copias de seguridad.

## Áreas de trabajo

El selector lateral define el periodo de Auditoría, Explorador SQL, Mapper y Homología persistente. Las reglas se evalúan con el historial completo y sus resultados se acotan al periodo. Mapper y Homología calculan sobre los pagos seleccionados. Validación de casos comprueba el inventario completo del extracto.

| Área | Qué se puede revisar |
| --- | --- |
| Auditoría | Indicadores de pagos únicos, tendencia mensual, categorías, reglas más frecuentes, las 29 reglas, evidencia, exportación y seguimiento de cada caso. |
| Explorador SQL | Ejecuta y muestra las consultas DuckDB de las 29 reglas. Permite combinar reglas, buscar por identificador, proveedor o cuenta y exportar los pagos o los registros del maestro que coinciden. |
| Mapper | Grafo DBSCAN sobre cuatro variables de comportamiento con lente, intervalos y solapamiento ajustables. Colorea los nodos por cualquiera de las 29 reglas y compara su tasa con el extracto. La ficha muestra importes, plazos, reglas coincidentes, evidencia y pagos fuera del grafo. Los hallazgos de maestro se pueden consultar como contexto del proveedor. |
| Homología persistente | Diagramas de Vietoris–Rips H₀/H₁, distancias de Wasserstein y ranking H₀ por pago. Compara comportamiento frente a comportamiento más las cuatro señales SQL en los mismos pagos. |
| Validación de casos | Resultado esperado y veredicto para cada caso documentado del extracto, con descarga CSV. |

La señal SQL de cuenta compartida se proyecta sobre los pagos de sus proveedores. La regla A05 cuenta el grupo de proveedores en el maestro. Los conteos corresponden a esas unidades distintas. Los casos sembrados son etiquetas parciales, por lo que la evaluación reporta cobertura de casos y coincidencia entre métodos. Los umbrales actuales son parámetros de simulación.

## Distribución del extracto simulado

El extracto contiene 5.399 pagos y 403 proveedores. Se ajustaron vencimientos para conservar 100 pagos tardíos (1,85 %), se redistribuyeron fechas de algunos pagos para reducir los casos de inactividad y se añadieron ejemplos a las reglas poco representadas mediante cambios dirigidos en los registros. Las frecuencias resultantes sirven para explorar el dashboard con datos simulados. El inventario de 269 casos documenta los ejemplos verificados.

## Referencia y pruebas

La organización en resumen, explorador y metodología sigue la [auditoría topológica de Topo](https://github.com/santirdzrmz/topologia/tree/main/auditoria-topologica), consultada en GitHub en la revisión `6872ba1`. El motor DuckDB, los parámetros, la validación y la persistencia proceden del dashboard descriptivo de este espacio de trabajo.

```sh
python -m unittest discover -s tests
```

Las pruebas comprueban los 269 casos de referencia, los nodos y solapamientos Mapper y la persistencia H₀/H₁ en nubes de puntos conocidas. Los módulos adaptados de Topo conservan su licencia en `LICENSE-Topo`.
