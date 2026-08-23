-- Base de datos de auditoria interna y compras en espanol (snake_case)

-- Tabla para guardar todas las transacciones del ERP
CREATE TABLE Compras_ERP (
    ID_Transaccion VARCHAR(50) PRIMARY KEY,
    Fecha_Transaccion TIMESTAMP NOT NULL,
    Nombre_Proveedor VARCHAR(255) NOT NULL,
    ID_Empleado VARCHAR(50) NOT NULL,
    Centro_Costo VARCHAR(100) NOT NULL,
    Monto NUMERIC(15, 2) NOT NULL,
    Moneda VARCHAR(3) NOT NULL,
    Descripcion TEXT
);

-- Tabla para los hallazgos reportados por la auditoria
CREATE TABLE Hallazgos_Auditoria (
    ID_Hallazgo VARCHAR(50) PRIMARY KEY,
    Fecha_Evaluacion TIMESTAMP NOT NULL,
    Regla_Detectada VARCHAR(100) NOT NULL,
    Nivel_Severidad VARCHAR(20) NOT NULL,
    Analisis_IA TEXT NOT NULL,
    Accion_Recomendada TEXT NOT NULL,
    Falso_Positivo BOOLEAN NOT NULL
);

-- Tabla intermedia para conectar los hallazgos con las transacciones que los causaron
CREATE TABLE Relacion_Hallazgos_Compras (
    ID_Hallazgo VARCHAR(50) REFERENCES Hallazgos_Auditoria(ID_Hallazgo) ON DELETE CASCADE,
    ID_Transaccion VARCHAR(50) REFERENCES Compras_ERP(ID_Transaccion) ON DELETE RESTRICT,
    PRIMARY KEY (ID_Hallazgo, ID_Transaccion)
);

-- Indices para buscar mas rapido por fecha, proveedor y empleado
CREATE INDEX idx_compras_fecha ON Compras_ERP(Fecha_Transaccion);
CREATE INDEX idx_compras_proveedor_monto ON Compras_ERP(Nombre_Proveedor, Monto, Fecha_Transaccion);
CREATE INDEX idx_compras_empleado_fecha ON Compras_ERP(ID_Empleado, Fecha_Transaccion);
