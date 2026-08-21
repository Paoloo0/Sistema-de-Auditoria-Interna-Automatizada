# Automatizando la Auditoría Interna con Python, SQL e Inteligencia Artificial

Este proyecto implementa un pipeline de datos para automatizar el monitoreo continuo de transacciones financieras y la detección de anomalías en compras. La solución extrae datos de un ERP (SQL), ejecuta reglas de negocio y análisis estadísticos en memoria (Pandas), evalúa el contexto cualitativo mediante Inteligencia Artificial (API de Gemini con Structured Outputs) y persiste los hallazgos validados de forma consistente en una base de datos relacional.

---

## 📌 El Problema

En las organizaciones tradicionales, la auditoría interna se enfrenta a dos desafíos críticos:
1. **Zonas ciegas por muestreo manual:** Revisar transacciones de forma manual consume demasiado tiempo, lo que obliga a los auditores a seleccionar solo un pequeño porcentaje de los datos (un 5% o 10%). Esto deja una gran cantidad de registros sin auditar, donde pueden pasar desapercibidos errores graves o fraudes.
2. **Alertas tradicionales ineficientes (Ruido):** Las reglas fijas tradicionales de los ERP suelen generar cientos de alertas irrelevantes (falsos positivos), lo que satura al equipo de cumplimiento y hace que pierdan el foco sobre los problemas verdaderamente críticos.
3. **Falta de criterio contextual:** Las herramientas matemáticas básicas pueden identificar que un monto es elevado, pero no pueden leer las descripciones de las facturas ni interpretar si un usuario está fraccionando un pago deliberadamente para saltarse los límites de aprobación.

---

## 💡 La Solución

Para solucionar esto, este proyecto propone un **embudo de procesamiento inteligente** estructurado en tres niveles que permite analizar el 100% de las transacciones de manera costo-eficiente:

1. **Extracción y Filtro Rápido (SQL):** Extracción incremental eficiente basada en índices de fecha para evitar sobrecargar los sistemas de producción.
2. **Motor de Reglas Deterministas (Python & Pandas):** Procesa miles de registros en segundos para buscar patrones sospechosos específicos (pagos duplicados, fraccionamiento de firmas y montos atípicos). Esto reduce el volumen a auditar a aproximadamente un ~1% de registros de interés.
3. **Validación Contextual (Gemini API con Pydantic):** La Inteligencia Artificial recibe únicamente este 1% de registros sospechosos. Su tarea no es hacer cálculos, sino leer las descripciones de las facturas y la relación entre transacciones para descartar falsas alarmas operativas y redactar un informe de auditoría detallado.

---

## 🛠️ Arquitectura del Sistema

El flujo de datos del pipeline está diseñado de la siguiente forma:

```
[ ERP Database ] ──( Extracción SQL Optimizada )──> [ Motor en Pandas ]
                                                            │
                                                     (Filtro de Anomalías)
                                                            │
                                                            ▼
[ BD de Auditoría ] <──( Persistencia SQL )── [ API de Gemini / Pydantic ]
```

*   **Capa SQL:** Extracción selectiva desde la tabla `erp_purchase_transactions` filtrando por ventanas de tiempo para evitar transferencias masivas de datos.
*   **Motor Pandas:** Aplica filtros vectorizados rápidos para detectar:
    *   **Duplicados:** Misma empresa, mismo monto y diferencia temporal < 24 horas.
    *   **Split Invoices (Fraccionamiento):** Compras de un mismo empleado al mismo proveedor en el mismo día, que individualmente son menores a $10,000 pero sumadas superan ese límite de aprobación corporativo.
    *   **Outliers Estadísticos:** Compras con un monto extremadamente inusual comparado con el promedio del Centro de Costo (Z-Score > 3.0).
*   **IA con Structured Outputs:** Evaluación cognitiva mediante el SDK de Gemini. Usamos esquemas de Pydantic para forzar al modelo a responder con un formato JSON estricto y prevenir que se rompa la integración.
*   **Persistencia Transaccional:** La capa final toma el JSON validado y lo guarda en la base de datos de auditoría usando transacciones seguras de SQLAlchemy (`commit` / `rollback`).

---

## 🗄️ Estructura de la Base de Datos

El diseño relacional incluye tres tablas principales y tres índices de optimización:

### Tablas:
1.  **`erp_purchase_transactions`:** Tabla origen del ERP que almacena las compras registradas con información de proveedores, montos, fechas, empleados y centros de costo.
2.  **`internal_audit_findings`:** Tabla destino que guarda el reporte final redactado por la IA, su nivel de riesgo y la clasificación de falso positivo.
3.  **`finding_transaction_association`:** Tabla intermedia que resuelve la relación de muchos a muchos (N:M). Un hallazgo (como un fraccionamiento) involucra varias transacciones individuales.

### Índices de Optimización:
*   `idx_trans_date`: Acelera la búsqueda incremental diaria por rangos de fecha.
*   `idx_trans_vendor_amount`: Optimiza las búsquedas de duplicidad agrupando proveedor y monto.
*   `idx_trans_employee_date`: Agiliza la detección de compras fraccionadas por empleado en un mismo día.

---

## 🚀 Instrucciones de Instalación y Uso

### 1. Clonar el repositorio
Abre tu terminal y clona el proyecto usando la siguiente URL:
```bash
git clone https://github.com/Paoloo0/Automatizando-la-Auditor-a-Interna-con-Python-SQL-e-Inteligencia-Artificial.git
cd Automatizando-la-Auditor-a-Interna-con-Python-SQL-e-Inteligencia-Artificial
```

### 2. Instalar dependencias
Asegúrate de tener instalado Python 3.10 o superior. Instala las librerías necesarias ejecutando:
```bash
pip install -r requirements.txt
```
*(Si prefieres usar `uv` como gestor de paquetes rápido, puedes usar `uv pip install -r requirements.txt`)*

### 3. Configurar la Base de Datos
Antes de correr el pipeline, debes crear las tablas en tu motor de base de datos relacional. Ejecuta el archivo SQL que contiene la estructura inicializada:
*   Archivo SQL: [`schema.sql`](schema.sql)

### 4. Configurar Variables de Entorno
Crea las variables en tu entorno antes de correr el script:
```bash
# En Windows (CMD):
set DATABASE_URL=postgresql://usuario:contraseña@servidor:5432/nombre_bd
set GEMINI_API_KEY=tu_api_key_de_gemini

# En Windows (PowerShell):
$env:DATABASE_URL="postgresql://usuario:contraseña@servidor:5432/nombre_bd"
$env:GEMINI_API_KEY="tu_api_key_de_gemini"
```
*Nota: Si no configuras una base de datos PostgreSQL, el script creará y usará automáticamente un archivo local de SQLite (`audit_internal.db`). Si no configuras la `GEMINI_API_KEY`, el pipeline usará respuestas simuladas altamente realistas para que puedas probarlo localmente sin costo.*

### 5. Ejecutar el Pipeline
Para correr el monitoreo y ver los resultados en consola y base de datos, ejecuta:
```bash
python pipeline.py
```
*(O con `uv`: `uv run pipeline.py`)*
