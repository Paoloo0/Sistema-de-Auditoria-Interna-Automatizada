-- Base de datos de auditoria interna y compras

-- Tabla para guardar todas las transacciones del ERP
CREATE TABLE erp_purchase_transactions (
    transaction_id VARCHAR(50) PRIMARY KEY,
    transaction_date TIMESTAMP NOT NULL,
    vendor_name VARCHAR(255) NOT NULL,
    employee_id VARCHAR(50) NOT NULL,
    cost_center VARCHAR(100) NOT NULL,
    amount NUMERIC(15, 2) NOT NULL,
    currency VARCHAR(3) NOT NULL,
    description TEXT
);

-- Tabla para los hallazgos reportados por la auditoria
CREATE TABLE internal_audit_findings (
    finding_id VARCHAR(50) PRIMARY KEY,
    evaluation_date TIMESTAMP NOT NULL,
    detected_rule VARCHAR(100) NOT NULL,
    severity_level VARCHAR(20) NOT NULL,
    audit_narrative TEXT NOT NULL,
    recommended_action TEXT NOT NULL,
    is_false_positive BOOLEAN NOT NULL
);

-- Tabla intermedia para conectar los hallazgos con las transacciones que los causaron
CREATE TABLE finding_transaction_association (
    finding_id VARCHAR(50) REFERENCES internal_audit_findings(finding_id) ON DELETE CASCADE,
    transaction_id VARCHAR(50) REFERENCES erp_purchase_transactions(transaction_id) ON DELETE RESTRICT,
    PRIMARY KEY (finding_id, transaction_id)
);

-- indices para buscar mas rapido por fecha, proveedor y empleado
CREATE INDEX idx_trans_date ON erp_purchase_transactions(transaction_date);
CREATE INDEX idx_trans_vendor_amount ON erp_purchase_transactions(vendor_name, amount, transaction_date);
CREATE INDEX idx_trans_employee_date ON erp_purchase_transactions(employee_id, transaction_date);
