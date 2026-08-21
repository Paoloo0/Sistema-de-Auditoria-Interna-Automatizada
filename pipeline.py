# -*- coding: utf-8 -*-
"""
Pipeline de datos para auditoria interna y control de calidad
Combina la conexion SQL, extraccion, motor de reglas de negocio en Pandas agrupando por empleado,
integracion con Gemini (estructurada con Pydantic) y persistencia transaccional.
"""

import os
import time
import json
import random
from datetime import datetime, timedelta
from typing import List, Dict, Any

import pandas as pd
import numpy as np
from pydantic import BaseModel, Field

# SQLAlchemy para la conexion relacional
from sqlalchemy import create_engine, text

# =====================================================================
# Estructura del Hallazgo de Auditoria (Pydantic para Gemini y BD)
# =====================================================================
class HallazgoAuditoria(BaseModel):
    finding_id: str = Field(description="ID unico del hallazgo, ej. AUD-2026-CONSOLIDATED-01")
    detected_rule: str = Field(description="Reglas rotas, ej. DUPLICATE_PAYMENT, SPLIT_INVOICE, u OUTLIER_AMOUNT")
    severity_level: str = Field(description="Riesgo: Low, Medium, High o Critical")
    audit_narrative: str = Field(description="Detalle completo de lo que se encontro tras el analisis")
    recommended_action: str = Field(description="Accion sugerida para corregir el problema")
    is_false_positive: bool = Field(description="True si es una falsa alarma contable, False si es un hallazgo real")
    associated_transaction_ids: List[str] = Field(description="Lista de IDs de las facturas que causaron esta alerta")


# =====================================================================
# Capa de Base de Datos (SQLAlchemy)
# =====================================================================

def conectar_db():
    # Usamos variable de entorno para Postgres o creamos un SQLite local para pruebas rapida
    url = os.environ.get("DATABASE_URL", "sqlite:///audit_internal.db")
    print(f"[*] Conectando a la base de datos en: {url}")
    
    try:
        engine = create_engine(url)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        print("[+] Conexion exitosa.")
        return engine
    except Exception as err:
        print(f"[-] Error de conexion: {err}")
        print("[*] Reintentando en 3 segundos...")
        time.sleep(3)
        return create_engine(url)


def cargar_datos_prueba(engine):
    # Validamos que la tabla exista antes de sembrar datos
    try:
        with engine.connect() as conn:
            total = conn.execute(text("SELECT COUNT(*) FROM erp_purchase_transactions")).scalar()
    except Exception as err:
        print(f"[-] La tabla erp_purchase_transactions no existe: {err}")
        print("[-] Por favor ejecuta primero el archivo 'schema.sql' en tu base de datos.")
        raise err
        
    if total > 0:
        print(f"[i] La tabla erp_purchase_transactions ya tiene {total} registros. No metemos datos de prueba.")
        return
        
    print("[*] Generando compras de prueba en el ERP...")
    
    proveedores = ['GLOBAL_TECH_INC', 'OFFICE_DEPOT_CORP', 'LOGISTICS_EXPRESS_SA', 'CONSULTING_GROUP_LLC', 'ENERGY_SUPPLY_CORP']
    empleados = ['EMP-102', 'EMP-204', 'EMP-305', 'EMP-401', 'EMP-500', 'EMP-999']
    centros_costo = ['IT_DEP', 'OPERATIONS_DEP', 'SALES_DEP', 'MARKETING_DEP', 'FINANCE_DEP']
    
    fecha_base = datetime(2026, 8, 1, 8, 0, 0)
    compras = []
    
    # Metemos 100 compras normales
    for i in range(1, 101):
        random.seed(i)
        np.random.seed(i)
        
        monto = round(float(np.random.exponential(scale=1000.0) + 15.0), 2)
        compras.append({
            "transaction_id": f"TX-{i:05d}",
            "transaction_date": fecha_base + timedelta(days=random.randint(0, 15), hours=random.randint(8, 17)),
            "vendor_name": random.choice(proveedores),
            "employee_id": random.choice(empleados),
            "cost_center": random.choice(centros_costo),
            "amount": monto,
            "currency": "USD",
            "description": "Compra normal de insumos y mantenimiento."
        })
        
    # Inyectamos las anomalias conocidas para probar las reglas
    
    # 1. Pago Duplicado (Mismo proveedor y monto, con diferencia de 15 minutos)
    fecha_dup = datetime(2026, 8, 5, 10, 30, 0)
    compras.append({
        "transaction_id": "TX-DUP-001A",
        "transaction_date": fecha_dup,
        "vendor_name": "GLOBAL_TECH_INC",
        "employee_id": "EMP-204",
        "cost_center": "IT_DEP",
        "amount": 4500.00,
        "currency": "USD",
        "description": "Licenciamiento anual de plataforma SaaS de analitica"
    })
    compras.append({
        "transaction_id": "TX-DUP-001B",
        "transaction_date": fecha_dup + timedelta(minutes=15),
        "vendor_name": "GLOBAL_TECH_INC",
        "employee_id": "EMP-204",
        "cost_center": "IT_DEP",
        "amount": 4500.00,
        "currency": "USD",
        "description": "Licenciamiento anual de plataforma SaaS de analitica (reproceso por timeout)"
    })
    
    # 2. Fraccionamiento / Split (Limite de firma individual $10k. Dos transacciones de $9.5k y $9k del mismo empleado)
    fecha_split = datetime(2026, 8, 8, 14, 0, 0)
    compras.append({
        "transaction_id": "TX-SPL-001A",
        "transaction_date": fecha_split,
        "vendor_name": "CONSULTING_GROUP_LLC",
        "employee_id": "EMP-305",
        "cost_center": "FINANCE_DEP",
        "amount": 9500.00,
        "currency": "USD",
        "description": "Servicios de consultoria financiera Fase I"
    })
    compras.append({
        "transaction_id": "TX-SPL-001B",
        "transaction_date": fecha_split + timedelta(minutes=12),
        "vendor_name": "CONSULTING_GROUP_LLC",
        "employee_id": "EMP-305",
        "cost_center": "FINANCE_DEP",
        "amount": 9000.00,
        "currency": "USD",
        "description": "Servicios de consultoria financiera Fase II"
    })
    
    # 3. Transaccion en Fin de Semana (Gasto mayor a $1,000 en domingo)
    fecha_we = datetime(2026, 8, 9, 23, 10, 0) # Domingo por la noche
    compras.append({
        "transaction_id": "TX-WE-001",
        "transaction_date": fecha_we,
        "vendor_name": "ENERGY_SUPPLY_CORP",
        "employee_id": "EMP-102",
        "cost_center": "OPERATIONS_DEP",
        "amount": 1200.00,
        "currency": "USD",
        "description": "Ajuste de inventario extraordinario en domingo"
    })
    
    # 4. Outlier Estadistico (Monto atipico extremo en el departamento)
    compras.append({
        "transaction_id": "TX-OUT-999",
        "transaction_date": datetime(2026, 8, 12, 11, 15, 0),
        "vendor_name": "ENERGY_SUPPLY_CORP",
        "employee_id": "EMP-999",
        "cost_center": "OPERATIONS_DEP",
        "amount": 145000.00,
        "currency": "USD",
        "description": "Renovacion de maquinaria critica y calderas de generacion"
    })
    
    query_insertar = text(
        """
        INSERT INTO erp_purchase_transactions 
        (transaction_id, transaction_date, vendor_name, employee_id, cost_center, amount, currency, description)
        VALUES (:transaction_id, :transaction_date, :vendor_name, :employee_id, :cost_center, :amount, :currency, :description)
        """
    )
    
    with engine.begin() as conn:
        conn.execute(query_insertar, compras)
        
    print(f"[+] Se agregaron {len(compras)} compras de prueba a la base de datos.")


def extraer_transacciones(engine, fecha_desde: datetime, fecha_hasta: datetime) -> pd.DataFrame:
    # Consulta SQL indexada por rango de fechas
    print(f"[*] Extrayendo compras del ERP desde {fecha_desde.date()} hasta {fecha_hasta.date()}...")
    
    query = text(
        """
        SELECT 
            transaction_id,
            transaction_date,
            vendor_name,
            employee_id,
            cost_center,
            amount,
            currency,
            description
        FROM erp_purchase_transactions
        WHERE transaction_date >= :start_date AND transaction_date <= :end_date
        ORDER BY transaction_date ASC
        """
    )
    
    with engine.connect() as conn:
        df = pd.read_sql_query(
            query, 
            conn, 
            params={"start_date": fecha_desde, "end_date": fecha_hasta}
        )
    return df


# =====================================================================
# Motor de Reglas en Pandas y Consolidacion
# =====================================================================

def aplicar_reglas_y_consolidar(df_crudo: pd.DataFrame) -> List[Dict[str, Any]]:
    """
    Aplica las 4 reglas logico-estadisticas y consolida las alertas agrupandolas
    por empleado para realizar evaluaciones relacionales y evitar spam de reportes.
    """
    if df_crudo.empty:
        return []
        
    print("[*] Procesando transacciones con el motor de reglas en Pandas...")
    df = df_crudo.copy()
    
    # Normalizamos tipos de datos en Pandas para trabajar seguros
    df['transaction_date'] = pd.to_datetime(df['transaction_date'])
    df['amount'] = pd.to_numeric(df['amount'])
    df['vendor_name'] = df['vendor_name'].str.strip().str.upper()
    df['employee_id'] = df['employee_id'].str.strip()
    df['cost_center'] = df['cost_center'].str.strip()
    
    # Extraemos variables para la regla del fin de semana
    df['dia_semana_num'] = df['transaction_date'].dt.weekday # 5=Sabado, 6=Domingo
    df['es_fin_semana'] = df['dia_semana_num'].isin([5, 6])
    
    # Lista donde acumularemos las alertas individuales antes de consolidar
    alertas_individuales = []

    # -----------------------------------------------------------------
    # REGLA 1: Pagos Duplicados (Mismo proveedor, monto y diferencia <= 24h)
    # -----------------------------------------------------------------
    df_ordenado = df.sort_values(by=['vendor_name', 'amount', 'transaction_date'])
    df_ordenado['diferencia_tiempo'] = df_ordenado.groupby(['vendor_name', 'amount'])['transaction_date'].diff()
    
    duplicados = df_ordenado[
        (df_ordenado['diferencia_tiempo'].notnull()) & 
        (df_ordenado['diferencia_tiempo'] <= pd.Timedelta(hours=24))
    ]
    
    for idx, fila in duplicados.iterrows():
        coincidencias = df[
            (df['vendor_name'] == fila['vendor_name']) &
            (df['amount'] == fila['amount']) &
            (df['transaction_id'] != fila['transaction_id']) &
            (abs(df['transaction_date'] - fila['transaction_date']) <= pd.Timedelta(hours=24))
        ]
        
        for idx_c, fila_c in coincidencias.iterrows():
            alertas_individuales.append({
                "transaction_id": fila_c['transaction_id'],
                "employee_id": fila_c['employee_id'],
                "cost_center": fila_c['cost_center'],
                "vendor_name": fila_c['vendor_name'],
                "amount": fila_c['amount'],
                "transaction_date": fila_c['transaction_date'],
                "description": fila_c['description'],
                "motivo_alerta": "DUPLICATE_PAYMENT",
                "detalle_alerta": f"Transaccion duplicada en monto (${fila_c['amount']:,.2f}) y proveedor con menos de 24h de diferencia."
            })

    # Marcamos que IDs ya fueron procesados como duplicados para no duplicar en las siguientes reglas
    ids_duplicados = {a['transaction_id'] for a in alertas_individuales}

    # -----------------------------------------------------------------
    # REGLA 2: Fraccionamiento de Compras (Splits para evadir limite de $10k)
    # -----------------------------------------------------------------
    df['fecha_dia'] = df['transaction_date'].dt.date
    df_menor_limite = df[df['amount'] < 10000.00]
    
    grupos_split = df_menor_limite.groupby(['employee_id', 'vendor_name', 'fecha_dia'])
    for (empleado, proveedor, dia), grupo in grupos_split:
        if len(grupo) > 1:
            total_dia = grupo['amount'].sum()
            if total_dia >= 10000.00:
                for idx, fila_g in grupo.iterrows():
                    # Evitamos meter duplicados si ya estaban reportados
                    if fila_g['transaction_id'] not in ids_duplicados:
                        alertas_individuales.append({
                            "transaction_id": fila_g['transaction_id'],
                            "employee_id": fila_g['employee_id'],
                            "cost_center": fila_g['cost_center'],
                            "vendor_name": fila_g['vendor_name'],
                            "amount": fila_g['amount'],
                            "transaction_date": fila_g['transaction_date'],
                            "description": fila_g['description'],
                            "motivo_alerta": "SPLIT_INVOICE",
                            "detalle_alerta": f"Posible fraccionamiento: Factura individual menor a $10k pero acumula ${total_dia:,.2f} en el mismo dia."
                        })

    ids_procesados = {a['transaction_id'] for a in alertas_individuales}

    # -----------------------------------------------------------------
    # REGLA 3: Transacciones en Fin de Semana (Gasto > $1,000 en sab/dom)
    # -----------------------------------------------------------------
    findes_sospechosos = df[(df['es_fin_semana']) & (df['amount'] > 1000.00)]
    for idx, fila_f in findes_sospechosos.iterrows():
        if fila_f['transaction_id'] not in ids_procesados:
            alertas_individuales.append({
                "transaction_id": fila_f['transaction_id'],
                "employee_id": fila_f['employee_id'],
                "cost_center": fila_f['cost_center'],
                "vendor_name": fila_f['vendor_name'],
                "amount": fila_f['amount'],
                "transaction_date": fila_f['transaction_date'],
                "description": fila_f['description'],
                "motivo_alerta": "WEEKEND_TRANSACTION",
                "detalle_alerta": f"Transaccion operada en fin de semana por un monto de ${fila_f['amount']:,.2f}, superando el limite de control de $1,000."
            })

    ids_procesados = {a['transaction_id'] for a in alertas_individuales}

    # -----------------------------------------------------------------
    # REGLA 4: Outliers Estadisticos (Z-Score > 3.0 agrupado por cost_center)
    # -----------------------------------------------------------------
    df['media_cc'] = df.groupby('cost_center')['amount'].transform('mean')
    df['desviacion_cc'] = df.groupby('cost_center')['amount'].transform('std')
    df['desviacion_cc'] = df['desviacion_cc'].replace(0, 1.0)
    df['z_score'] = (df['amount'] - df['media_cc']) / df['desviacion_cc']
    
    outliers = df[df['z_score'] > 3.0]
    for idx, fila_o in outliers.iterrows():
        if fila_o['transaction_id'] not in ids_procesados:
            alertas_individuales.append({
                "transaction_id": fila_o['transaction_id'],
                "employee_id": fila_o['employee_id'],
                "cost_center": fila_o['cost_center'],
                "vendor_name": fila_o['vendor_name'],
                "amount": fila_o['amount'],
                "transaction_date": fila_o['transaction_date'],
                "description": fila_o['description'],
                "motivo_alerta": "OUTLIER_AMOUNT",
                "detalle_alerta": f"El monto de ${fila_o['amount']:,.2f} representa un comportamiento atipico en el departamento (Z-Score = {fila_o['z_score']:.2f})."
            })

    # -----------------------------------------------------------------
    # Agrupacion y Consolidacion por Empleado
    # -----------------------------------------------------------------
    consolidados = {}
    for alerta in alertas_individuales:
        emp_id = alerta['employee_id']
        if emp_id not in consolidados:
            consolidados[emp_id] = {
                "employee_id": emp_id,
                "cost_center": alerta['cost_center'],
                "alertas_detectadas": set(),
                "transacciones_sospechosas": [],
                "transaction_ids": set()
            }
            
        consolidados[emp_id]["alertas_detectadas"].add(alerta['motivo_alerta'])
        consolidados[emp_id]["transaction_ids"].add(alerta['transaction_id'])
        
        # Estructuramos la transaccion para el payload de la IA
        consolidados[emp_id]["transacciones_sospechosas"].append({
            "transaction_id": alerta['transaction_id'],
            "transaction_date": str(alerta['transaction_date']),
            "vendor_name": alerta['vendor_name'],
            "amount": float(alerta['amount']),
            "description": alerta['description'],
            "detalle_alerta": alerta['detalle_alerta'],
            "motivo_alerta": alerta['motivo_alerta']
        })

    # Formateamos el resultado final para retornar
    lista_consolidados = []
    for emp_id, datos in consolidados.items():
        lista_consolidados.append({
            "clave": f"CONSOLIDATED-{emp_id}-{datetime.now().strftime('%Y%m%d')}",
            "employee_id": emp_id,
            "cost_center": datos["cost_center"],
            "rules_violated": list(datos["alertas_detectadas"]),
            "transaction_ids": list(datos["transaction_ids"]),
            "amount_sum": sum(tx["amount"] for tx in datos["transacciones_sospechosas"]),
            "records": datos["transacciones_sospechosas"]
        })
        
    print(f"[+] Reglas ejecutadas y consolidadas. Encontramos {len(lista_consolidados)} perfiles de empleados con alertas.")
    return lista_consolidados


# =====================================================================
# Evaluacion Inteligente con Gemini
# =====================================================================

def llamar_gemini(lote: Dict[str, Any], api_key: str) -> HallazgoAuditoria:
    from google import genai
    from google.genai import types
    
    client = genai.Client(api_key=api_key)
    
    instrucciones = f"""
    Eres un auditor contable evaluando posibles fraudes o errores.
    Analiza el siguiente perfil transaccional consolidado para el empleado '{lote['employee_id']}' en el departamento '{lote['cost_center']}':
    
    - Reglas del sistema violadas: {lote['rules_violated']}
    - Suma total bajo alerta: USD {lote['amount_sum']:,.2f}
    
    Transacciones sospechosas del empleado:
    {json.dumps(lote['records'], default=str, indent=2)}
    
    Evalua si el conjunto de alertas tiene logica operativa normal o si es sospechoso.
    Devuelve la respuesta estructurada bajo el formato JSON del esquema:
    - finding_id: Codigo unico como AUD-2026-CONSOLIDATED-XXX
    - detected_rule: Junta las reglas rotas separadas por comas, ej. {', '.join(lote['rules_violated'])}
    - severity_level: Low, Medium, High o Critical
    - audit_narrative: Narrativa formal que analice la relacion de las compras y su riesgo corporativo
    - recommended_action: Acciones inmediatas sugeridas al equipo de control
    - is_false_positive: True si consideras que es una operacion comun de la empresa, False si amerita investigar
    - associated_transaction_ids: Devuelve exactamente los IDs del lote: {lote['transaction_ids']}
    """
    
    response = client.models.generate_content(
        model='gemini-2.5-flash',
        contents=instrucciones,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=HallazgoAuditoria,
            temperature=0.1,
            system_instruction="Escribe tus informes de auditoria con tono formal, profesional y en español."
        )
    )
    
    datos = json.loads(response.text)
    return HallazgoAuditoria(**datos)


def simular_respuesta_ia(lote: Dict[str, Any]) -> HallazgoAuditoria:
    # Genera una respuesta simulada realista para ejecucion local
    reglas = lote['rules_violated']
    ids = lote['transaction_ids']
    emp = lote['employee_id']
    id_random = random.randint(100, 999)
    anio = datetime.now().year
    
    # Redactamos segun la combinacion de reglas encontradas en el lote
    if "SPLIT_INVOICE" in reglas:
        narrativa = (
            f"Se identifico un posible fraccionamiento de compras (Split Invoice) realizado por el empleado {emp} "
            f"hacia el proveedor {lote['records'][0]['vendor_name']} el dia 2026-08-08. Las transacciones individuales "
            f"fueron emitidas en un rango de 12 minutos por montos de $9,500.00 y $9,000.00 para mantenerse por debajo "
            f"del limite de firma de $10,000.00, sumando un total de $18,500.00 que requeria firmas adicionales."
        )
        accion = "Retener pagos pendientes al proveedor, iniciar investigacion con el empleado y reportar a la gerencia."
        severidad = "Critical"
        es_falso = False
        
    elif "DUPLICATE_PAYMENT" in reglas:
        narrativa = (
            f"Se detecto un pago duplicado confirmado para el empleado {emp} con el proveedor GLOBAL_TECH_INC. "
            f"Se pasaron dos facturas identicas de $4,500.00 con solo 15 minutos de diferencia. La descripcion de la "
            f"segunda indica '(reproceso por timeout)', confirmando que fue un error en la carga y aprobacion del sistema."
        )
        accion = f"Iniciar proceso de devolucion de saldo o emision de nota de credito por $4,500.00 con el proveedor."
        severidad = "High"
        es_falso = False
        
    elif "WEEKEND_TRANSACTION" in reglas:
        narrativa = (
            f"El empleado {emp} registro una transaccion de ajuste de inventario el domingo por la noche por $1,200.00. "
            f"Si bien las transacciones dominicales estan restringidas, la descripcion y el monto sugieren que se trata "
            f"de una operacion de inventario programada de fin de mes, catalogada como operacion habitual autorizada."
        )
        accion = "Confirmar asistencia del empleado con el supervisor de bodega y archivar como soporte."
        severidad = "Low"
        es_falso = True # Marcado como falsa alarma
        
    else: # OUTLIER_AMOUNT
        narrativa = (
            f"El empleado {emp} registro un pago extraordinario de ${lote['amount_sum']:,.2f} para {lote['records'][0]['vendor_name']}. "
            f"Esta compra excede de manera atipica el promedio de gastos de su departamento (Z-Score > 3.0), representando "
            f"un desvio del presupuesto asignado sin acta de aprobacion adjunta."
        )
        accion = "Solicitar contrato firmado del proyecto, cotizaciones alternativas y firmas de autorizacion de la direccion."
        severidad = "High"
        es_falso = False

    return HallazgoAuditoria(
        finding_id=f"AUD-{anio}-CONSOLIDATED-{id_random}",
        detected_rule=", ".join(reglas),
        severity_level=severidad,
        audit_narrative=narrativa,
        recommended_action=accion,
        is_false_positive=es_falso,
        associated_transaction_ids=ids
    )


# =====================================================================
# Persistencia
# =====================================================================

def guardar_hallazgos(engine, hallazgos: List[HallazgoAuditoria]):
    if not hallazgos:
        print("[i] No hay hallazgos para registrar en la base de datos.")
        return
        
    print(f"[*] Guardando {len(hallazgos)} hallazgos validados en la base de datos...")
    
    # Sentencias SQL directas sin IF NOT EXISTS
    if engine.url.drivername == "sqlite":
        sql_hallazgo = text(
            """
            INSERT OR REPLACE INTO internal_audit_findings 
            (finding_id, evaluation_date, detected_rule, severity_level, audit_narrative, recommended_action, is_false_positive)
            VALUES (:finding_id, :evaluation_date, :detected_rule, :severity_level, :audit_narrative, :recommended_action, :is_false_positive)
            """
        )
        sql_puente = text(
            """
            INSERT OR IGNORE INTO finding_transaction_association (finding_id, transaction_id)
            VALUES (:finding_id, :transaction_id)
            """
        )
    else:
        sql_hallazgo = text(
            """
            INSERT INTO internal_audit_findings 
            (finding_id, evaluation_date, detected_rule, severity_level, audit_narrative, recommended_action, is_false_positive)
            VALUES (:finding_id, :evaluation_date, :detected_rule, :severity_level, :audit_narrative, :recommended_action, :is_false_positive)
            ON CONFLICT (finding_id) DO UPDATE SET
                evaluation_date = EXCLUDED.evaluation_date,
                severity_level = EXCLUDED.severity_level,
                audit_narrative = EXCLUDED.audit_narrative,
                recommended_action = EXCLUDED.recommended_action,
                is_false_positive = EXCLUDED.is_false_positive
            """
        )
        sql_puente = text(
            """
            INSERT INTO finding_transaction_association (finding_id, transaction_id)
            VALUES (:finding_id, :transaction_id)
            ON CONFLICT DO NOTHING
            """
        )
        
    try:
        # Hacemos el guardado usando una sola transaccion atomica segura
        with engine.begin() as conn:
            for hallazgo in hallazgos:
                conn.execute(
                    sql_hallazgo,
                    {
                        "finding_id": hallazgo.finding_id,
                        "evaluation_date": datetime.now(),
                        "detected_rule": hallazgo.detected_rule,
                        "severity_level": hallazgo.severity_level,
                        "audit_narrative": hallazgo.audit_narrative,
                        "recommended_action": hallazgo.recommended_action,
                        "is_false_positive": hallazgo.is_false_positive
                    }
                )
                
                for tx_id in hallazgo.associated_transaction_ids:
                    conn.execute(
                        sql_puente,
                        {
                            "finding_id": hallazgo.finding_id,
                            "transaction_id": tx_id
                        }
                    )
        print("[+] Persistencia relacional finalizada exitosamente.")
    except Exception as err:
        print(f"[-] Error al insertar registros en la base de datos: {err}")
        print("[-] Se deshicieron todas las operaciones de este lote (Rollback ejecutado).")


# =====================================================================
# Orquestacion
# =====================================================================

def correr_pipeline():
    print("=" * 60)
    print(" INICIANDO PIPELINE CONSOLIDADO DE AUDITORIA INTERNA")
    print("=" * 60)
    
    # 1. Conexion
    db_engine = conectar_db()
    
    # 2. Inyeccion inicial (Si la base esta vacia)
    cargar_datos_prueba(db_engine)
    
    # 3. Extraccion incremental desde el ERP
    fecha_ini = datetime(2026, 8, 1, 0, 0, 0)
    fecha_fin = datetime(2026, 8, 20, 23, 59, 59)
    df = extraer_transacciones(db_engine, fecha_ini, fecha_fin)
    
    # 4. Busqueda de alertas y consolidacion por empleado
    alertas_consolidadas = aplicar_reglas_y_consolidar(df)
    
    if not alertas_consolidadas:
        print("[i] No se encontraron transacciones sospechosas el dia de hoy.")
        return
        
    # 5. Analisis cognitivo (Gemini o simulador local)
    api_key = os.environ.get("GEMINI_API_KEY", "")
    hallazgos = []
    
    for i, lote in enumerate(alertas_consolidadas, 1):
        print(f"[*] Evaluando perfil consolidado {i} de {len(alertas_consolidadas)}...")
        
        if api_key:
            if i > 1:
                time.sleep(2) # Respetamos limites de rate limit de Gemini gratis
            try:
                hallazgo = llamar_gemini(lote, api_key)
            except Exception as err:
                print(f"[-] Error llamando a Gemini: {err}. Usando simulador.")
                hallazgo = simular_respuesta_ia(lote)
        else:
            hallazgo = simular_respuesta_ia(lote)
            
        hallazgos.append(hallazgo)
        
    # 6. Persistencia de hallazgos
    guardar_hallazgos(db_engine, hallazgos)
    
    # Reporte de cierre por consola
    print("\n" + "=" * 60)
    print("          REPORTE DE HALLAZGOS CONSOLIDADOS")
    print("=" * 60)
    for h in hallazgos:
        tipo = "Falsa Alarma" if h.is_false_positive else "Alerta Confirmada"
        print(f"\nHallazgo: {h.finding_id} | Reglas: {h.detected_rule} | Riesgo: {h.severity_level} ({tipo})")
        print(f"  Narrativa: {h.audit_narrative}")
        print(f"  Accion contable: {h.recommended_action}")
        print(f"  Facturas asociadas: {h.associated_transaction_ids}")
        print("-" * 60)
        
    print("\n[+] Monitoreo consolidado finalizado.")
    print("=" * 60)


if __name__ == "__main__":
    correr_pipeline()
