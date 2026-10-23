-- Optional manual migration for existing SQL Server deployments.
-- The application also detects and adds this nullable column at startup.
IF COL_LENGTH('delivery_orders','created_by') IS NULL
BEGIN
    ALTER TABLE delivery_orders ADD created_by VARCHAR(36) NULL REFERENCES users(id);
    CREATE INDEX ix_delivery_orders_created_by ON delivery_orders(created_by);
END;
GO
-- Old orders are preserved with created_by=NULL. Existing roles are unchanged.
