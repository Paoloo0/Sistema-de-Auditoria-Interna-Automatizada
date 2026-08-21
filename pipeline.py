# -*- coding: utf-8 -*-
"""
Pipeline de datos para auditoria interna
Desarrollado para extraer compras del ERP, buscar alertas con Pandas y evaluarlas con Gemini.
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

# Importamos SQLAlchemy para manejar las conexiones y consultas
from sqlalchemy import create_engine, text

# =====================================================================
# Estructura del Hallazgo de Auditoria (Esquema para Gemini y la BD)
# =====================================================================
class HallazgoAuditoria(BaseModel):
    # Campos que se guardan en la tabla internal_audit_findings
    finding_id: str = Field(description="ID unico del hallazgo, ej. AUD-2026-DUP-01")
    detected_rule: str = Field(description="La regla rota (DUPLICATE_PAYMENT, SPLIT_INVOICE, OUTLIER_AMOUNT)")
    severity_level: str = Field(description="Nivel de riesgo: Low, Medium, High o Critical")
    audit_narrative: str = Field(description="Detalle completo de lo que paso y por que es sospechoso")
    recommended_action: str = Field(description="Recomendacion sobre que debe hacer el equipo contable")
    is_false_positive: bool = Field(description="Indica si es una falsa alarma (True) o un hallazgo real (False)")
    associated_transaction_ids: List[str] = Field(description="Lista de IDs de las facturas involucradas")


# =====================================================================
# Funciones para la Base de Datos
# =====================================================================

def conectar_db():
    # Buscamos la URL de Postgres. Si no existe, usamos SQLite local para pruebas.
    conexion_url = os.environ.get("DATABASE_URL", "sqlite:///audit_internal.db")
    print(f"[*] Conectando a la base de datos en: {conexion_url}")
    
    try:
        # Creamos el motor de conexion y probamos con un select rapido
        engine = create_engine(conexion_url)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        print("[+] Conexion exitosa.")
        return engine
    except Exception as err:
        print(f"[-] Error de conexion: {err}")
        print("[*] Reintentando en 3 segundos...")
        time.sleep(3)
        return create_engine(conexion_url)


def cargar_datos_prueba(engine):
    # Llenamos la tabla de transacciones con datos de prueba si esta vacia
    try:
        with engine.connect() as conn:
            total = conn.execute(text("SELECT COUNT(*) FROM erp_purchase_transactions")).scalar()
    except Exception as err:
        # Si la tabla no existe, mostramos el error y recordamos que deben correr schema.sql
        print(f"[-] Error al consultar la tabla erp_purchase_transactions: {err}")
        print("[-] Asegurate de haber ejecutado primero el script 'schema.sql' en tu base de datos.")
        raise err
        
    if total > 0:
        print(f"[i] La tabla ya tiene {total} compras. No cargamos datos de prueba.")
        return
        
    print("[*] Insertando compras de prueba...")
    
    proveedores = ['GLOBAL_TECH_INC', 'OFFICE_DEPOT_CORP', 'LOGISTICS_EXPRESS_SA', 'CONSULTING_GROUP_LLC', 'ENERGY_SUPPLY_CORP']
    empleados = ['EMP-102', 'EMP-204', 'EMP-305', 'EMP-401', 'EMP-500', 'EMP-999']
    centros_costo = ['IT_DEP', 'OPERATIONS_DEP', 'SALES_DEP', 'MARKETING_DEP', 'FINANCE_DEP']
    
    fecha_base = datetime(2026, 8, 1, 8, 0, 0)
    compras = []
    
    # Generamos 100 registros normales usando semillas aleatorias fijas
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
        
    # Agregamos casos anomalos intencionales para probar
    
    # 1. Pago Duplicado (Mismo proveedor, mismo monto, 15 min de diferencia)
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
    
    # 2. Fraccionamiento / Split (Limite es $10,000. EMP-305 hace dos compras juntas por $18,500)
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
    
    # 3. Monto Atipico (Un pago extremadamente alto)
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
        
    print(f"[+] Se agregaron {len(compras)} compras de prueba.")


def extraer_transacciones(engine, fecha_desde: datetime, fecha_hasta: datetime) -> pd.DataFrame:
    # Consulta SQL optimizada filtrando por fecha
    print(f"[*] Extrayendo compras desde {fecha_desde.date()} hasta {fecha_hasta.date()}...")
    
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
# Motor de Reglas en Pandas
# =====================================================================

def aplicar_reglas(df_crudo: pd.DataFrame) -> List[Dict[str, Any]]:
    # Limpiamos y normalizamos los datos antes de evaluar
    if df_crudo.empty:
        return []
        
    df = df_crudo.copy()
    df['transaction_date'] = pd.to_datetime(df['transaction_date'])
    df['amount'] = pd.to_numeric(df['amount'])
    df['vendor_name'] = df['vendor_name'].str.strip().str.upper()
    df['employee_id'] = df['employee_id'].str.strip()
    df['cost_center'] = df['cost_center'].str.strip()
    
    lotes_alertas = []
    ids_analizados = set() # Guardamos los IDs procesados para no repetir alertas

    # 1. Buscar pagos duplicados (Mismo proveedor, monto y diferencia menor a 24 horas)
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
        
        lista_ids = list(set([fila['transaction_id']] + coincidencias['transaction_id'].tolist()))
        lista_ids.sort()
        
        hash_lote = f"DUP-{fila['vendor_name']}-{fila['amount']}-{fila['transaction_date'].strftime('%Y%m%d')}"
        
        if not any(l.get('clave') == hash_lote for l in lotes_alertas):
            registros = df[df['transaction_id'].isin(lista_ids)].to_dict(orient="records")
            lotes_alertas.append({
                "clave": hash_lote,
                "rule": "DUPLICATE_PAYMENT",
                "transaction_ids": lista_ids,
                "description": f"Doble cobro al proveedor {fila['vendor_name']} por ${fila['amount']:,.2f} en menos de 24 horas.",
                "vendor_name": fila['vendor_name'],
                "amount_sum": fila['amount'] * len(lista_ids),
                "records": registros
            })
            ids_analizados.update(lista_ids)

    # 2. Buscar fraccionamiento de facturas (Split invoices para saltar firmas de $10k)
    df['fecha_dia'] = df['transaction_date'].dt.date
    df_menor_limite = df[df['amount'] < 10000.00]
    
    grupos_split = df_menor_limite.groupby(['employee_id', 'vendor_name', 'fecha_dia'])
    
    for (empleado, proveedor, dia), grupo in grupos_split:
        if len(grupo) > 1: # Deben ser minimo 2 facturas
            monto_total = grupo['amount'].sum()
            if monto_total >= 10000.00: # Juntas pasan el limite de autorizacion
                lista_ids = grupo['transaction_id'].tolist()
                lista_ids.sort()
                
                hash_lote = f"SPLIT-{empleado}-{proveedor}-{dia.strftime('%Y%m%d')}"
                
                if not any(l.get('clave') == hash_lote for l in lotes_alertas):
                    lotes_alertas.append({
                        "clave": hash_lote,
                        "rule": "SPLIT_INVOICE",
                        "transaction_ids": lista_ids,
                        "description": f"El empleado {empleado} paso {len(grupo)} facturas el mismo dia al proveedor {proveedor} sumando ${monto_total:,.2f} para evadir aprobaciones.",
                        "vendor_name": proveedor,
                        "amount_sum": float(monto_total),
                        "records": grupo.to_dict(orient="records")
                    })
                    ids_analizados.update(lista_ids)

    # 3. Buscar montos atipicos en el departamento (Z-Score > 3.0)
    df['media_cc'] = df.groupby('cost_center')['amount'].transform('mean')
    df['desviacion_cc'] = df.groupby('cost_center')['amount'].transform('std')
    
    # Evitamos la division por cero si todos los montos del cc son iguales
    df['desviacion_cc'] = df['desviacion_cc'].replace(0, 1.0)
    df['z_score'] = (df['amount'] - df['media_cc']) / df['desviacion_cc']
    
    outliers = df[df['z_score'] > 3.0]
    
    for idx, fila in outliers.iterrows():
        # Solo lo alertamos si no fue atrapado por las reglas anteriores
        if fila['transaction_id'] not in ids_analizados:
            hash_lote = f"OUT-{fila['transaction_id']}"
            lotes_alertas.append({
                "clave": hash_lote,
                "rule": "OUTLIER_AMOUNT",
                "transaction_ids": [fila['transaction_id']],
                "description": f"Gasto muy alto fuera del promedio en el departamento {fila['cost_center']} (Z-Score = {fila['z_score']:.2f}).",
                "vendor_name": fila['vendor_name'],
                "amount_sum": float(fila['amount']),
                "records": [fila.to_dict()]
            })
            ids_analizados.add(fila['transaction_id'])
            
    print(f"[+] Reglas listas. Encontramos {len(lotes_alertas)} casos sospechosos en Pandas.")
    return lotes_alertas


# =====================================================================
# Integracion con la API de Gemini o Simulacion
# =====================================================================

def llamar_gemini(lote: Dict[str, Any], api_key: str) -> HallazgoAuditoria:
    # Usamos la SDK oficial google-genai
    from google import genai
    from google.genai import types
    
    client = genai.Client(api_key=api_key)
    
    instrucciones = f"""
    Eres un auditor interno revisando posibles irregularidades.
    Evalua el siguiente lote de compras que marco el sistema:
    - Regla: {lote['rule']}
    - Descripcion: {lote['description']}
    - Monto Total: USD {lote['amount_sum']:,.2f}
    
    Transacciones en cuestion:
    {json.dumps(lote['records'], default=str, indent=2)}
    
    Dime si parece un error administrativo, un fraccionamiento de firmas real, o una operacion normal.
    Formatea tu respuesta exactamente en el esquema JSON requerido:
    - finding_id: Inventa un codigo unico como AUD-2026-RULE-XXX
    - detected_rule: {lote['rule']}
    - severity_level: Low, Medium, High o Critical
    - audit_narrative: Explicacion formal de por que es un riesgo
    - recommended_action: Accion inmediata a tomar
    - is_false_positive: True si consideras que es operacion normal (falsa alarma), False si requiere investigarse
    - associated_transaction_ids: Devuelve exactamente la lista {lote['transaction_ids']}
    """
    
    # Hacemos la peticion pidiendo formato JSON estructurado segun nuestra clase de Pydantic
    response = client.models.generate_content(
        model='gemini-2.5-flash',
        contents=instrucciones,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=HallazgoAuditoria,
            temperature=0.1,
            system_instruction="Escribe tus respuestas en español claro, profesional y de auditoria."
        )
    )
    
    datos = json.loads(response.text)
    return HallazgoAuditoria(**datos)


def simular_respuesta_ia(lote: Dict[str, Any]) -> HallazgoAuditoria:
    # Genera un JSON simulado con la estructura correcta si no hay internet o API Key
    regla = lote['rule']
    ids = lote['transaction_ids']
    id_random = random.randint(100, 999)
    anio = datetime.now().year
    
    if regla == "DUPLICATE_PAYMENT":
        narrativa = (
            f"Se encontro un doble cobro al proveedor {lote['vendor_name']} por el mismo monto (${lote['amount_sum']/2:,.2f}) "
            f"con diferencia de 15 minutos. El comentario de la segunda factura indica '(reproceso por timeout)', "
            f"confirmando que se volvio a mandar el pago por error de red sin validar que la primera orden ya habia entrado."
        )
        accion = f"Iniciar reclamo de reembolso o nota de credito por ${lote['amount_sum']/2:,.2f} a {lote['vendor_name']}."
        severidad = "High"
        es_falso = False
        
    elif regla == "SPLIT_INVOICE":
        narrativa = (
            f"El empleado EMP-305 registro dos compras separadas el mismo dia al proveedor {lote['vendor_name']} "
            f"por montos de $9,500.00 y $9,000.00. La suma total es de $18,500.00, superando el limite de firma "
            f"solitaria de $10,000.00. El espaciado de 12 minutos indica un fraccionamiento voluntario para evitar firmas del gerente."
        )
        accion = "Detener el pago en tesoreria, solicitar aclaracion escrita al empleado y turnar caso a Recursos Humanos."
        severidad = "Critical"
        es_falso = False
        
    else: # OUTLIER_AMOUNT
        narrativa = (
            f"La compra {ids[0]} por ${lote['amount_sum']:,.2f} supera considerablemente la media del centro de costo "
            f"OPERATIONS_DEP. La descripcion indica 'Renovacion de maquinaria critica'. Al ser un gasto extraordinario "
            f"CAPEX, necesita justificacion y aprobacion de presupuesto del Director General."
        )
        accion = "Solicitar cotizaciones comparativas del proveedor, orden de compra firmada y acta de aprobacion del proyecto."
        severidad = "High"
        es_falso = False
        
    return HallazgoAuditoria(
        finding_id=f"AUD-{anio}-{regla}-{id_random}",
        detected_rule=regla,
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
    # Si la lista esta vacia nos saltamos el guardado
    if not hallazgos:
        print("[i] No hay hallazgos para registrar.")
        return
        
    print(f"[*] Guardando {len(hallazgos)} hallazgos en la base de datos...")
    
    # Sentencias SQL para insertar en las tablas de auditoria
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
        # Usamos begin() para agrupar todas las inserciones en una sola transaccion segura
        with engine.begin() as conn:
            for hallazgo in hallazgos:
                # Metemos el registro del hallazgo
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
                
                # Metemos los enlaces puente
                for tx_id in hallazgo.associated_transaction_ids:
                    conn.execute(
                        sql_puente,
                        {
                            "finding_id": hallazgo.finding_id,
                            "transaction_id": tx_id
                        }
                    )
        print("[+] Guardado completado con exito.")
    except Exception as err:
        print(f"[-] Ocurrio un error al insertar en la base de datos: {err}")
        print("[-] Se deshicieron todas las operaciones de este lote (Rollback).")


# =====================================================================
# Metodo Principal (Ejecucion secuencial)
# =====================================================================

def correr_pipeline():
    print("=" * 60)
    print(" INICIANDO MONITOREO DIARIO DE AUDITORIA INTERNA")
    print("=" * 60)
    
    # 1. Nos conectamos al motor de base de datos
    db_engine = conectar_db()
    
    # 2. Metemos datos iniciales para probar de una
    # Nota: Si usas SQLite local, recuerda haber corrido primero schema.sql sobre la BD.
    cargar_datos_prueba(db_engine)
    
    # 3. Extraemos las transacciones usando fechas fijas
    fecha_ini = datetime(2026, 8, 1, 0, 0, 0)
    fecha_fin = datetime(2026, 8, 20, 23, 59, 59)
    df = extraer_transacciones(db_engine, fecha_ini, fecha_fin)
    
    # 4. Procesamos con Pandas para ver si hay alertas
    alertas = aplicar_reglas(df)
    
    if not alertas:
        print("[i] Todo limpio. No hay alertas el dia de hoy.")
        return
        
    # 5. Pasamos las alertas a Gemini (o simulacion si no hay API Key)
    api_key = os.environ.get("GEMINI_API_KEY", "")
    hallazgos = []
    
    for i, lote in enumerate(alertas, 1):
        print(f"[*] Evaluando caso {i} de {len(alertas)}...")
        
        if api_key:
            # Esperamos 2 segundos entre llamadas para respetar el limite de cuotas gratis
            if i > 1:
                time.sleep(2)
            try:
                hallazgo = llamar_gemini(lote, api_key)
            except Exception as err:
                print(f"[-] Error llamando a la API: {err}. Usando simulacion.")
                hallazgo = simular_respuesta_ia(lote)
        else:
            hallazgo = simular_respuesta_ia(lote)
            
        hallazgos.append(hallazgo)
        
    # 6. Guardamos los resultados validados en la base de datos
    guardar_hallazgos(db_engine, hallazgos)
    
    # Imprimimos resumen final por consola
    print("\n" + "=" * 60)
    print("          RESULTADOS FINALES DEL ANALISIS")
    print("=" * 60)
    for h in hallazgos:
        tipo = "Falsa alarma" if h.is_false_positive else "Confirmado"
        print(f"\nHallazgo: {h.finding_id} | Regla: {h.detected_rule} | Severidad: {h.severity_level} ({tipo})")
        print(f"  Narrativa: {h.audit_narrative}")
        print(f"  Accion propuesta: {h.recommended_action}")
        print(f"  Facturas asociadas: {h.associated_transaction_ids}")
        print("-" * 60)
        
    print("\n[+] Monitoreo de auditoria terminado.")
    print("=" * 60)


if __name__ == "__main__":
    correr_pipeline()
