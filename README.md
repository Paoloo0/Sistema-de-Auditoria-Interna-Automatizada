# Sistema de Auditoría Interna Automatizada

Este proyecto implementa un pipeline de datos inteligente para el monitoreo continuo de transacciones financieras y la detección de anomalías en compras corporativas. El sistema combina un motor lógico en Pandas, una validación cognitiva con Inteligencia Artificial (API de Gemini con Structured Outputs) y una integración directa con base de datos relacionales y flujos automatizados de Power Platform (Power Automate).

---

## 📌 El Problema (Contexto de Auditoría)

En las organizaciones medianas y grandes se realizan miles de compras al día. La práctica tradicional de auditoría interna se enfrenta a limitaciones críticas:
1. **Muestreo manual ineficiente:** Por falta de tiempo, los auditores seleccionan al azar entre el 5% y 10% de las transacciones para revisarlas a detalle. El otro 90% queda en una "caja negra" sin supervisar, creando zonas ciegas donde ocurren errores de pago o fraudes reales.
2. **Fatiga de alertas por falsos positivos:** Las reglas tradicionales de los sistemas ERP (como alertar por cada transacción realizada en fin de semana) saturan a los auditores con cientos de falsas alarmas, haciendo que ignoren riesgos críticos reales.
3. **Falta de criterio contextual:** Las computadoras tradicionales pueden detectar si un monto supera cierto valor, pero no pueden leer la descripción escrita de una factura ni entender si un empleado está fraccionando un pago deliberadamente en varias compras menores para eludir los límites de aprobación corporativos.

---

## 💡 La Solución

Este proyecto implementa un **embudo híbrido de detección en tres etapas** que permite analizar el 100% de las transacciones de manera costo-eficiente, asegurando la cobertura del análisis y la integridad de los controles corporativos:

1. **Filtro Estructurado y SQL:** Extracción selectiva desde la base de datos ERP basada en rangos de fechas e índices para no afectar los sistemas en producción.
2. **Motor de Reglas y Agrupamiento (Pandas):** Procesa el volumen masivo de datos en milisegundos para buscar anomalías lógicas y estadísticas (duplicados, fraccionamientos de firmas, transacciones fuera de horario laboral y montos atípicos). Las alertas se consolidan por empleado para evaluar perfiles de comportamiento diario y reducir los registros sospechosos al ~1% de interés.
3. **Validación Contextual y Redacción (Gemini API):** La Inteligencia Artificial actúa como filtro de criterio final. Lee las descripciones de las facturas y los datos de las transacciones agrupadas para descartar falsas alarmas operativas (falsos positivos) y redactar un informe formal en JSON estructurado de forma automatizada.

---

## 🛠️ Arquitectura del Proyecto

El sistema se compone de dos grandes capas: el backend de procesamiento de datos en Python y el frontend de automatización y notificaciones en Power Platform:

```
[ ERP Database ] ──( Extracción SQL )──> [ Python / Pandas Engine ]
                                                 │
                                        (Consolidación por Empleado)
                                                 │
                                                 ▼
[ BD de Auditoría ] <──( SQLAlchemy )── [ Gemini API (Pydantic) ]
                                                 │
                                         (Exportación JSON)
                                                 │
                                                 ▼
                                     [ hallazgos_auditoria.json ]
                                                 │
                                          (Sincronización)
                                                 │
                                                 ▼
                                      [ OneDrive for Business ]
                                                 │
                                           (Trigger Flow)
                                                 │
                                                 ▼
                                     [ MS Power Automate ]
                                                 │
                                     ┌───────────┴───────────┐
                                     ▼                       ▼
                              [ MS Teams Alert ]      [ Outlook Report ]
```

El script de Python procesa las transacciones y exporta los hallazgos validados a un archivo local llamado `hallazgos_auditoria.json`. Al estar este archivo sincronizado con la nube (OneDrive/SharePoint), actúa como el puente físico y disparador para los flujos en **Power Automate**, quienes se encargan de entregar las alertas a los auditores mediante notificaciones interactivas en Teams y correos en Outlook.

---

## ⚙️ Pipeline de Datos (Flujo Técnico)

El procesamiento del pipeline en Python sigue un flujo lineal y consistente:

1. **Extracción (SQL):** Conexión a la base de datos ERP (PostgreSQL/SQLite) mediante SQLAlchemy. Se ejecuta una consulta que extrae únicamente los datos comprendidos en la ventana de fecha de análisis.
2. **Procesamiento de Reglas (Pandas):**
   - *DUPLICATE_PAYMENT:* Busca registros contiguos del mismo proveedor y monto con menos de 24 horas de diferencia.
   - *SPLIT_INVOICE:* Agrupa compras menores al límite de firma ($10,000) hechas por el mismo usuario y proveedor en la misma fecha, comprobando si su suma supera el límite.
   - *WEEKEND_TRANSACTION:* Identifica movimientos mayores a $1,000 realizados en sábados o domingos.
   - *OUTLIER_AMOUNT:* Calcula desviaciones estándar por departamento y etiqueta compras que superen las 3 sigmas (Z-Score > 3.0).
3. **Consolidación de Perfil:** Agrupa las alertas individuales por `employee_id` creando un único perfil diario sospechoso por usuario para optimizar llamadas a la API de IA.
4. **Enriquecimiento con IA (Gemini API):** Envía el perfil a la API con un esquema Pydantic para validar riesgos contables y descartar falsos positivos operativos.
5. **Persistencia Relacional (SQLAlchemy):** Guarda de forma atómica el veredicto en la tabla `internal_audit_findings` y relaciona las facturas sospechosas usando la tabla asociativa `finding_transaction_association`.
6. **Exportación JSON:** Escribe los resultados confirmados a `hallazgos_auditoria.json` para dar inicio a la capa de automatización.

---

## 🤖 Manual de Automatización (Power Automate)

Para integrar los hallazgos validados con los canales corporativos de comunicación, se diseña un flujo automatizado en Microsoft Power Automate siguiendo la siguiente configuración de ingeniería:

### Paso 1: Trigger (Disparador)
- **Acción:** `OneDrive for Business - When a file is created (properties only)` o `When a file is modified`.
- **Configuración:**
  - **Folder:** Ruta de la carpeta compartida donde el script de Python exporta el archivo.
  - **File:** `hallazgos_auditoria.json`.
- **Sub-paso:** Agregar una acción `Get file content` usando el `Unique Identifier` provisto por el disparador para obtener los datos binarios del archivo.

### Paso 2: Data Parsing (Procesamiento del JSON)
- **Acción:** `Data Operation - Parse JSON`.
- **Content:** Salida (body) de la acción `Get file content`.
- **Esquema (Schema):** Copia y pega el siguiente esquema JSON estructurado generado a partir de nuestro modelo de Pydantic:
```json
{
  "type": "array",
  "items": {
    "type": "object",
    "properties": {
      "finding_id": { "type": "string" },
      "detected_rule": { "type": "string" },
      "severity_level": { "type": "string" },
      "audit_narrative": { "type": "string" },
      "recommended_action": { "type": "string" },
      "is_false_positive": { "type": "boolean" },
      "associated_transaction_ids": {
        "type": "array",
        "items": { "type": "string" }
      }
    },
    "required": [
      "finding_id",
      "detected_rule",
      "severity_level",
      "audit_narrative",
      "recommended_action",
      "is_false_positive",
      "associated_transaction_ids"
    ]
  }
}
```

### Paso 3: Workflow (Lógica y Filtro)
- **Acción:** Bucle `Apply to each` utilizando como entrada la salida del paso *Parse JSON*.
- **Condición Lógica:** Agregar una acción `Condition` dentro del bucle.
  - **Condición:** `is_false_positive` es igual a `false`.
  - **Acción Si Sí (Hallazgos Confirmados):** Procede a enviar alertas críticas.
  - **Acción Si No (Falsas Alarmas):** Finaliza el flujo o archiva el registro para reportería general de falsos positivos contables.

### Paso 4: Notificación (Acciones de Alerta)
Para los hallazgos reales (`is_false_positive` = false):
1. **Microsoft Teams:** Agregar la acción `Post card in a chat or channel`.
   - **Card:** Adaptar los campos del JSON (`finding_id`, `detected_rule`, `severity_level` y `audit_narrative`) a una plantilla de *Adaptive Card* con un botón que apunte a la base de datos de auditoría.
2. **Outlook:** Agregar la acción `Send an email (V2)`.
   - **Destinatarios:** Equipo de Auditoría Interna / Cumplimiento.
   - **Asunto:** `[ALERTA CRÍTICA DE COMPRAS] Hallazgo Contable - {severity_level}`.
   - **Cuerpo:** Incluye el reporte narrativo detallado y las acciones recomendadas generadas por el pipeline.

---

## 💻 Stack Tecnológico

El proyecto está construido sobre las siguientes herramientas:
- **Lenguaje:** Python 3.10+
- **Procesamiento de Datos:** Pandas, NumPy
- **Motor Relacional & ORM:** SQLAlchemy (driver `psycopg2` para Postgres y `sqlite` nativo)
- **Validación de Datos:** Pydantic (Structured Outputs)
- **Motor de Inteligencia Artificial:** Google Gemini API (modelo `gemini-2.5-flash` mediante `google-genai` SDK)
- **Integraciones:** Microsoft Power Automate, Microsoft Teams, Office 365

---

## 🚀 Instrucciones de Despliegue

### 1. Clonar el Proyecto
Descarga el código en tu máquina local:
```bash
git clone https://github.com/Paoloo0/Sistema-de-Auditor-a-Interna-Automatizada.git
cd Sistema-de-Auditor-a-Interna-Automatizada
```

### 2. Instalar Dependencias
Instala los paquetes necesarios definidos en el archivo `requirements.txt`:
```bash
pip install -r requirements.txt
```

### 3. Configurar Base de Datos
Crea las tablas en tu base de datos (PostgreSQL/SQLite) corriendo el archivo DDL de inicialización limpia:
- Archivo SQL: [`schema.sql`](schema.sql)

### 4. Configurar Variables de Entorno
Configura las credenciales en tu sistema antes de lanzar el script:

**En Windows (PowerShell):**
```powershell
$env:DATABASE_URL="postgresql://usuario:contraseña@servidor:5432/nombre_bd"
$env:GEMINI_API_KEY="tu_api_key_de_gemini"
```

**En Windows (CMD):**
```cmd
set DATABASE_URL=postgresql://usuario:contraseña@servidor:5432/nombre_bd
set GEMINI_API_KEY=tu_api_key_de_gemini
```

*Nota: Si no defines una URL en `DATABASE_URL`, el pipeline se conectará a un archivo SQLite local (`audit_internal.db`). Si la variable `GEMINI_API_KEY` no se encuentra, el script correrá en modo simulación estructurada, permitiendo probar todo el flujo de forma gratuita y sin conexión.*

### 5. Ejecutar el Pipeline
Para correr el script de extremo a extremo, ejecuta:
```bash
python pipeline.py
```
*(O con `uv`: `uv run pipeline.py`)*
