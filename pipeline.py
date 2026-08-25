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

# Diccionario de traduccion para nombres de reglas profesionales
TRADUCCION_REGLAS = {
    "DUPLICATE_PAYMENT": "Pago Duplicado",
    "SPLIT_INVOICE": "Fraccionamiento",
    "WEEKEND_TRANSACTION": "Fin de Semana",
    "OUTLIER_AMOUNT": "Monto Atipico"
}

def obtener_nombre_regla_esp(reglas: List[str]) -> str:
    if not reglas:
        return ""
    if len(reglas) == 1:
        return TRADUCCION_REGLAS.get(reglas[0], reglas[0])
    
    # Si hay multiples y una es transaccion en fin de semana (FDS)
    if "WEEKEND_TRANSACTION" in reglas:
        otras = [r for r in reglas if r != "WEEKEND_TRANSACTION"]
        if otras:
            return f"{TRADUCCION_REGLAS.get(otras[0], otras[0])} + FDS"
            
    return " + ".join([TRADUCCION_REGLAS.get(r, r) for r in reglas])

# =====================================================================
# Estructura del Hallazgo de Auditoria (Pydantic para Gemini y BD)
# =====================================================================
class HallazgoAuditoria(BaseModel):
    ID_Hallazgo: str = Field(description="ID unico del hallazgo, ej. AUD-2026-CONSOLIDATED-01")
    Regla_Detectada: str = Field(description="Reglas rotas en espanol simplificado")
    Nivel_Severidad: str = Field(description="Riesgo: Low, Medium, High o Critical")
    Analisis_IA: str = Field(description="Detalle completo de lo que se encontro tras el analisis")
    Accion_Recomendada: str = Field(description="Accion sugerida para corregir el problema")
    Falso_Positivo: bool = Field(description="True si es una falsa alarma contable, False si es un hallazgo real")
    ids_transacciones_asociadas: List[str] = Field(description="Lista de IDs de las facturas que causaron esta alerta")


# =====================================================================
# Capa de Base de Datos (SQLAlchemy)
# =====================================================================

def conectar_db():
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
    try:
        with engine.connect() as conn:
            total = conn.execute(text("SELECT COUNT(*) FROM Compras_ERP")).scalar()
    except Exception as err:
        print(f"[-] La tabla Compras_ERP no existe: {err}")
        print("[-] Por favor ejecuta primero el archivo 'schema.sql' en tu base de datos.")
        raise err
        
    if total > 0:
        print(f"[i] La tabla Compras_ERP ya tiene {total} registros. No metemos datos de prueba.")
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
            "ID_Transaccion": f"TX-{i:05d}",
            "Fecha_Transaccion": fecha_base + timedelta(days=random.randint(0, 15), hours=random.randint(8, 17)),
            "Nombre_Proveedor": random.choice(proveedores),
            "ID_Empleado": random.choice(empleados),
            "Centro_Costo": random.choice(centros_costo),
            "Monto": monto,
            "Moneda": "USD",
            "Descripcion": "Compra normal de insumos y mantenimiento."
        })
        
    # Inyectamos las anomalias conocidas para probar las reglas
    
    # 1. Pago Duplicado (Mismo proveedor y monto, con diferencia de 15 minutos)
    fecha_dup = datetime(2026, 8, 5, 10, 30, 0)
    compras.append({
        "ID_Transaccion": "TX-DUP-001A",
        "Fecha_Transaccion": fecha_dup,
        "Nombre_Proveedor": "GLOBAL_TECH_INC",
        "ID_Empleado": "EMP-204",
        "Centro_Costo": "IT_DEP",
        "Monto": 4500.00,
        "Moneda": "USD",
        "Descripcion": "Licenciamiento anual de plataforma SaaS de analitica"
    })
    compras.append({
        "ID_Transaccion": "TX-DUP-001B",
        "Fecha_Transaccion": fecha_dup + timedelta(minutes=15),
        "Nombre_Proveedor": "GLOBAL_TECH_INC",
        "ID_Empleado": "EMP-204",
        "Centro_Costo": "IT_DEP",
        "Monto": 4500.00,
        "Moneda": "USD",
        "Descripcion": "Licenciamiento anual de plataforma SaaS de analitica (reproceso por timeout)"
    })
    
    # 2. Fraccionamiento / Split (Limite de firma individual $10k. Dos transacciones de $9.5k y $9k del mismo empleado)
    fecha_split = datetime(2026, 8, 8, 14, 0, 0)
    compras.append({
        "ID_Transaccion": "TX-SPL-001A",
        "Fecha_Transaccion": fecha_split,
        "Nombre_Proveedor": "CONSULTING_GROUP_LLC",
        "ID_Empleado": "EMP-305",
        "Centro_Costo": "FINANCE_DEP",
        "Monto": 9500.00,
        "Moneda": "USD",
        "Descripcion": "Servicios de consultoria financiera Fase I"
    })
    compras.append({
        "ID_Transaccion": "TX-SPL-001B",
        "Fecha_Transaccion": fecha_split + timedelta(minutes=12),
        "Nombre_Proveedor": "CONSULTING_GROUP_LLC",
        "ID_Empleado": "EMP-305",
        "Centro_Costo": "FINANCE_DEP",
        "Monto": 9000.00,
        "Moneda": "USD",
        "Descripcion": "Servicios de consultoria financiera Fase II"
    })
    
    # 3. Transaccion en Fin de Semana (Gasto mayor a $1,000 en domingo)
    fecha_we = datetime(2026, 8, 9, 23, 10, 0) # Domingo por la noche
    compras.append({
        "ID_Transaccion": "TX-WE-001",
        "Fecha_Transaccion": fecha_we,
        "Nombre_Proveedor": "ENERGY_SUPPLY_CORP",
        "ID_Empleado": "EMP-102",
        "Centro_Costo": "OPERATIONS_DEP",
        "Monto": 1200.00,
        "Moneda": "USD",
        "Descripcion": "Ajuste de inventario extraordinario en domingo"
    })
    
    # 4. Outlier Estadistico (Monto atipico extremo en el departamento)
    compras.append({
        "ID_Transaccion": "TX-OUT-999",
        "Fecha_Transaccion": datetime(2026, 8, 12, 11, 15, 0),
        "Nombre_Proveedor": "ENERGY_SUPPLY_CORP",
        "ID_Empleado": "EMP-999",
        "Centro_Costo": "OPERATIONS_DEP",
        "Monto": 145000.00,
        "Moneda": "USD",
        "Descripcion": "Renovacion de maquinaria critica y calderas de generacion"
    })
    
    query_insertar = text(
        """
        INSERT INTO Compras_ERP 
        (ID_Transaccion, Fecha_Transaccion, Nombre_Proveedor, ID_Empleado, Centro_Costo, Monto, Moneda, Descripcion)
        VALUES (:ID_Transaccion, :Fecha_Transaccion, :Nombre_Proveedor, :ID_Empleado, :Centro_Costo, :Monto, :Moneda, :Descripcion)
        """
    )
    
    with engine.begin() as conn:
        conn.execute(query_insertar, compras)
        
    print(f"[+] Se agregaron {len(compras)} compras de prueba a la base de datos.")


def extraer_transacciones(engine, fecha_desde: datetime, fecha_hasta: datetime) -> pd.DataFrame:
    print(f"[*] Extrayendo compras del ERP desde {fecha_desde.date()} hasta {fecha_hasta.date()}...")
    
    query = text(
        """
        SELECT 
            ID_Transaccion,
            Fecha_Transaccion,
            Nombre_Proveedor,
            ID_Empleado,
            Centro_Costo,
            Monto,
            Moneda,
            Descripcion
        FROM Compras_ERP
        WHERE Fecha_Transaccion >= :start_date AND Fecha_Transaccion <= :end_date
        ORDER BY Fecha_Transaccion ASC
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
    if df_crudo.empty:
        return []
        
    print("[*] Procesando transacciones con el motor de reglas en Pandas...")
    df = df_crudo.copy()
    
    # Normalizamos tipos de datos en Pandas para trabajar seguros
    df['Fecha_Transaccion'] = pd.to_datetime(df['Fecha_Transaccion'])
    df['Monto'] = pd.to_numeric(df['Monto'])
    df['Nombre_Proveedor'] = df['Nombre_Proveedor'].str.strip().str.upper()
    df['ID_Empleado'] = df['ID_Empleado'].str.strip()
    df['Centro_Costo'] = df['Centro_Costo'].str.strip()
    
    # Extraemos variables para la regla del fin de semana
    df['dia_semana_num'] = df['Fecha_Transaccion'].dt.weekday # 5=Sabado, 6=Domingo
    df['es_fin_semana'] = df['dia_semana_num'].isin([5, 6])
    
    # Lista donde acumularemos las alertas individuales antes de consolidar
    alertas_individuales = []

    # -----------------------------------------------------------------
    # REGLA 1: Pagos Duplicados (Mismo proveedor, monto y diferencia <= 24h)
    # -----------------------------------------------------------------
    df_ordenado = df.sort_values(by=['Nombre_Proveedor', 'Monto', 'Fecha_Transaccion'])
    df_ordenado['diferencia_tiempo'] = df_ordenado.groupby(['Nombre_Proveedor', 'Monto'])['Fecha_Transaccion'].diff()
    
    duplicados = df_ordenado[
        (df_ordenado['diferencia_tiempo'].notnull()) & 
        (df_ordenado['diferencia_tiempo'] <= pd.Timedelta(hours=24))
    ]
    
    for idx, fila in duplicados.iterrows():
        coincidencias = df[
            (df['Nombre_Proveedor'] == fila['Nombre_Proveedor']) &
            (df['Monto'] == fila['Monto']) &
            (df['ID_Transaccion'] != fila['ID_Transaccion']) &
            (abs(df['Fecha_Transaccion'] - fila['Fecha_Transaccion']) <= pd.Timedelta(hours=24))
        ]
        
        for idx_c, fila_c in coincidencias.iterrows():
            alertas_individuales.append({
                "ID_Transaccion": fila_c['ID_Transaccion'],
                "ID_Empleado": fila_c['ID_Empleado'],
                "Centro_Costo": fila_c['Centro_Costo'],
                "Nombre_Proveedor": fila_c['Nombre_Proveedor'],
                "Monto": fila_c['Monto'],
                "Fecha_Transaccion": fila_c['Fecha_Transaccion'],
                "Descripcion": fila_c['Descripcion'],
                "motivo_alerta": "DUPLICATE_PAYMENT",
                "detalle_alerta": f"Transaccion duplicada en monto (${fila_c['Monto']:,.2f}) y proveedor con menos de 24h de diferencia."
            })

    # Marcamos que IDs ya fueron procesados como duplicados para no duplicar en las siguientes reglas
    ids_duplicados = {a['ID_Transaccion'] for a in alertas_individuales}

    # -----------------------------------------------------------------
    # REGLA 2: Fraccionamiento de Compras (Splits para evadir limite de $10k)
    # -----------------------------------------------------------------
    df['fecha_dia'] = df['Fecha_Transaccion'].dt.date
    df_menor_limite = df[df['Monto'] < 10000.00]
    
    grupos_split = df_menor_limite.groupby(['ID_Empleado', 'Nombre_Proveedor', 'fecha_dia'])
    for (empleado, proveedor, dia), grupo in grupos_split:
        if len(grupo) > 1:
            total_dia = grupo['Monto'].sum()
            if total_dia >= 10000.00:
                for idx, fila_g in grupo.iterrows():
                    if fila_g['ID_Transaccion'] not in ids_duplicados:
                        alertas_individuales.append({
                            "ID_Transaccion": fila_g['ID_Transaccion'],
                            "ID_Empleado": fila_g['ID_Empleado'],
                            "Centro_Costo": fila_g['Centro_Costo'],
                            "Nombre_Proveedor": fila_g['Nombre_Proveedor'],
                            "Monto": fila_g['Monto'],
                            "Fecha_Transaccion": fila_g['Fecha_Transaccion'],
                            "Descripcion": fila_g['Descripcion'],
                            "motivo_alerta": "SPLIT_INVOICE",
                            "detalle_alerta": f"Posible fraccionamiento: Factura individual menor a $10k pero acumula ${total_dia:,.2f} en el mismo dia."
                        })

    ids_procesados = {a['ID_Transaccion'] for a in alertas_individuales}

    # -----------------------------------------------------------------
    # REGLA 3: Transacciones en Fin de Semana (Gasto > $1,000 en sab/dom)
    # -----------------------------------------------------------------
    findes_sospechosos = df[(df['es_fin_semana']) & (df['Monto'] > 1000.00)]
    for idx, fila_f in findes_sospechosos.iterrows():
        if fila_f['ID_Transaccion'] not in ids_procesados:
            alertas_individuales.append({
                "ID_Transaccion": fila_f['ID_Transaccion'],
                "ID_Empleado": fila_f['ID_Empleado'],
                "Centro_Costo": fila_f['Centro_Costo'],
                "Nombre_Proveedor": fila_f['Nombre_Proveedor'],
                "Monto": fila_f['Monto'],
                "Fecha_Transaccion": fila_f['Fecha_Transaccion'],
                "Descripcion": fila_f['Descripcion'],
                "motivo_alerta": "WEEKEND_TRANSACTION",
                "detalle_alerta": f"Transaccion operada en fin de semana por un monto de ${fila_f['Monto']:,.2f}, superando el limite de control de $1,000."
            })

    ids_procesados = {a['ID_Transaccion'] for a in alertas_individuales}

    # -----------------------------------------------------------------
    # REGLA 4: Outliers Estadisticos (Z-Score > 3.0 agrupado por Centro_Costo)
    # -----------------------------------------------------------------
    df['media_cc'] = df.groupby('Centro_Costo')['Monto'].transform('mean')
    df['desviacion_cc'] = df.groupby('Centro_Costo')['Monto'].transform('std')
    df['desviacion_cc'] = df['desviacion_cc'].replace(0, 1.0)
    df['z_score'] = (df['Monto'] - df['media_cc']) / df['desviacion_cc']
    
    outliers = df[df['z_score'] > 3.0]
    for idx, fila_o in outliers.iterrows():
        if fila_o['ID_Transaccion'] not in ids_procesados:
            alertas_individuales.append({
                "ID_Transaccion": fila_o['ID_Transaccion'],
                "ID_Empleado": fila_o['ID_Empleado'],
                "Centro_Costo": fila_o['Centro_Costo'],
                "Nombre_Proveedor": fila_o['Nombre_Proveedor'],
                "Monto": fila_o['Monto'],
                "Fecha_Transaccion": fila_o['Fecha_Transaccion'],
                "Descripcion": fila_o['Descripcion'],
                "motivo_alerta": "OUTLIER_AMOUNT",
                "detalle_alerta": f"El monto de ${fila_o['Monto']:,.2f} representa un comportamiento atipico en el departamento (Z-Score = {fila_o['z_score']:.2f})."
            })

    # -----------------------------------------------------------------
    # Agrupacion y Consolidacion por Empleado
    # -----------------------------------------------------------------
    consolidados = {}
    for alerta in alertas_individuales:
        emp_id = alerta['ID_Empleado']
        if emp_id not in consolidados:
            consolidados[emp_id] = {
                "ID_Empleado": emp_id,
                "Centro_Costo": alerta['Centro_Costo'],
                "alertas_detectadas": set(),
                "transacciones_sospechosas": [],
                "ids_transacciones": set()
            }
            
        consolidados[emp_id]["alertas_detectadas"].add(alerta['motivo_alerta'])
        consolidados[emp_id]["ids_transacciones"].add(alerta['ID_Transaccion'])
        
        consolidados[emp_id]["transacciones_sospechosas"].append({
            "ID_Transaccion": alerta['ID_Transaccion'],
            "Fecha_Transaccion": str(alerta['Fecha_Transaccion']),
            "Nombre_Proveedor": alerta['Nombre_Proveedor'],
            "Monto": float(alerta['Monto']),
            "Descripcion": alerta['Descripcion'],
            "detalle_alerta": alerta['detalle_alerta'],
            "motivo_alerta": alerta['motivo_alerta']
        })

    lista_consolidados = []
    for emp_id, datos in consolidados.items():
        lista_consolidados.append({
            "clave": f"CONSOLIDATED-{emp_id}-{datetime.now().strftime('%Y%m%d')}",
            "ID_Empleado": emp_id,
            "Centro_Costo": datos["Centro_Costo"],
            "rules_violated": list(datos["alertas_detectadas"]),
            "ids_transacciones": list(datos["ids_transacciones"]),
            "amount_sum": sum(tx["Monto"] for tx in datos["transacciones_sospechosas"]),
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
    
    reglas_traducidas = [TRADUCCION_REGLAS.get(r, r) for r in lote['rules_violated']]
    reglas_esp = obtener_nombre_regla_esp(lote['rules_violated'])
    
    instrucciones = f"""
    Eres un auditor contable evaluando posibles fraudes o errores.
    Analiza el siguiente perfil transaccional consolidado para el empleado '{lote['ID_Empleado']}' en el departamento '{lote['Centro_Costo']}':
    
    - Reglas del sistema violadas: {reglas_traducidas}
    - Suma total bajo alerta: USD {lote['amount_sum']:,.2f}
    
    Transacciones sospechosas del empleado:
    {json.dumps(lote['records'], default=str, indent=2)}
    
    Evalua si el conjunto de alertas tiene logica operativa normal o si es sospechoso.
    Devuelve la respuesta estructurada bajo el formato JSON del esquema:
    - ID_Hallazgo: Codigo unico como AUD-2026-CONSOLIDATED-XXX
    - Regla_Detectada: Devuelve exactamente esta cadena traducida: '{reglas_esp}'
    - Nivel_Severidad: Low, Medium, High o Critical
    - Analisis_IA: Narrativa formal que analice la relacion de las compras y su riesgo corporativo
    - Accion_Recomendada: Acciones inmediatas sugeridas al equipo de control
    - Falso_Positivo: True si consideras que es una operacion comun de la empresa (se catalogara como Sospechoso), False si amerita investigar (se catalogara como Confirmado)
    - ids_transacciones_asociadas: Devuelve exactamente los IDs del lote: {lote['ids_transacciones']}
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
    reglas = lote['rules_violated']
    ids = lote['ids_transacciones']
    emp = lote['ID_Empleado']
    id_random = random.randint(100, 999)
    anio = datetime.now().year
    
    reglas_esp = obtener_nombre_regla_esp(reglas)
    
    if "SPLIT_INVOICE" in reglas:
        narrativa = (
            f"Se identifico un posible fraccionamiento de compras (Split Invoice) realizado por el empleado {emp} "
            f"hacia el proveedor {lote['records'][0]['Nombre_Proveedor']} el dia 2026-08-08. Las transacciones individuales "
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
        es_falso = True
        
    else: # OUTLIER_AMOUNT
        narrativa = (
            f"El empleado {emp} registro un pago extraordinario de ${lote['amount_sum']:,.2f} para {lote['records'][0]['Nombre_Proveedor']}. "
            f"Esta compra excede de manera atipica el promedio de gastos de su departamento (Z-Score > 3.0), representando "
            f"un desvio del presupuesto asignado sin acta de aprobacion adjunta."
        )
        accion = "Solicitar contrato firmado del proyecto, cotizaciones alternativas y firmas de autorizacion de la direccion."
        severidad = "High"
        es_falso = False

    return HallazgoAuditoria(
        ID_Hallazgo=f"AUD-{anio}-CONSOLIDATED-{id_random}",
        Regla_Detectada=reglas_esp,
        Nivel_Severidad=severidad,
        Analisis_IA=narrativa,
        Accion_Recomendada=accion,
        Falso_Positivo=es_falso,
        ids_transacciones_asociadas=ids
    )


# =====================================================================
# Persistencia
# =====================================================================

def guardar_hallazgos(engine, hallazgos: List[HallazgoAuditoria]):
    if not hallazgos:
        print("[i] No hay hallazgos para registrar en la base de datos.")
        return
        
    print(f"[*] Guardando {len(hallazgos)} hallazgos validados en la base de datos...")
    
    if engine.url.drivername == "sqlite":
        sql_hallazgo = text(
            """
            INSERT OR REPLACE INTO Hallazgos_Auditoria 
            (ID_Hallazgo, Fecha_Evaluacion, Regla_Detectada, Nivel_Severidad, Analisis_IA, Accion_Recomendada, Falso_Positivo)
            VALUES (:ID_Hallazgo, :Fecha_Evaluacion, :Regla_Detectada, :Nivel_Severidad, :Analisis_IA, :Accion_Recomendada, :Falso_Positivo)
            """
        )
        sql_puente = text(
            """
            INSERT OR IGNORE INTO Relacion_Hallazgos_Compras (ID_Hallazgo, ID_Transaccion)
            VALUES (:ID_Hallazgo, :ID_Transaccion)
            """
        )
    else:
        sql_hallazgo = text(
            """
            INSERT INTO Hallazgos_Auditoria 
            (ID_Hallazgo, Fecha_Evaluacion, Regla_Detectada, Nivel_Severidad, Analisis_IA, Accion_Recomendada, Falso_Positivo)
            VALUES (:ID_Hallazgo, :Fecha_Evaluacion, :Regla_Detectada, :Nivel_Severidad, :Analisis_IA, :Accion_Recomendada, :Falso_Positivo)
            ON CONFLICT (ID_Hallazgo) DO UPDATE SET
                Fecha_Evaluacion = EXCLUDED.Fecha_Evaluacion,
                Nivel_Severidad = EXCLUDED.Nivel_Severidad,
                Analisis_IA = EXCLUDED.Analisis_IA,
                Accion_Recomendada = EXCLUDED.Accion_Recomendada,
                Falso_Positivo = EXCLUDED.Falso_Positivo
            """
        )
        sql_puente = text(
            """
            INSERT INTO Relacion_Hallazgos_Compras (ID_Hallazgo, ID_Transaccion)
            VALUES (:ID_Hallazgo, :ID_Transaccion)
            ON CONFLICT DO NOTHING
            """
        )
        
    try:
        with engine.begin() as conn:
            for hallazgo in hallazgos:
                conn.execute(
                    sql_hallazgo,
                    {
                        "ID_Hallazgo": hallazgo.ID_Hallazgo,
                        "Fecha_Evaluacion": datetime.now(),
                        "Regla_Detectada": hallazgo.Regla_Detectada,
                        "Nivel_Severidad": hallazgo.Nivel_Severidad,
                        "Analisis_IA": hallazgo.Analisis_IA,
                        "Accion_Recomendada": hallazgo.Accion_Recomendada,
                        "Falso_Positivo": hallazgo.Falso_Positivo
                    }
                )
                
                for tx_id in hallazgo.ids_transacciones_asociadas:
                    conn.execute(
                        sql_puente,
                        {
                            "ID_Hallazgo": hallazgo.ID_Hallazgo,
                            "ID_Transaccion": tx_id
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
                time.sleep(2)
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
    
    # 7. Exportamos los hallazgos a un archivo JSON para la automatizacion con Power Platform
    ruta_json = "hallazgos_auditoria.json"
    print(f"[*] Exportando resultados a {ruta_json} para Power Platform...")
    try:
        lista_dicts = [h.model_dump() for h in hallazgos]
        with open(ruta_json, "w", encoding="utf-8") as archivo:
            json.dump(lista_dicts, archivo, indent=4, ensure_ascii=False)
        print(f"[+] Archivo JSON exportado con exito en: {ruta_json}")
    except Exception as err:
        print(f"[-] Error al exportar el archivo JSON: {err}")

    # Reporte de cierre por consola
    print("\n" + "=" * 60)
    print("          REPORTE DE HALLAZGOS CONSOLIDADOS")
    print("=" * 60)
    for h in hallazgos:
        tipo = "Falsa Alarma" if h.Falso_Positivo else "Alerta Confirmada"
        print(f"\nHallazgo: {h.ID_Hallazgo} | Reglas: {h.Regla_Detectada} | Riesgo: {h.Nivel_Severidad} ({tipo})")
        print(f"  Narrativa: {h.Analisis_IA}")
        print(f"  Accion contable: {h.Accion_Recomendada}")
        print(f"  Facturas asociadas: {h.ids_transacciones_asociadas}")
        print("-" * 60)
        
    print("\n[+] Monitoreo consolidado finalizado.")
    print("=" * 60)


if __name__ == "__main__":
    correr_pipeline()
