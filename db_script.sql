IF NOT EXISTS (SELECT * FROM sys.databases WHERE name = 'AgentBotDB')
BEGIN
    CREATE DATABASE AgentBotDB;
END
GO

-- 1. Таблиця для задач аналізу (результати роботи агентів)
IF OBJECT_ID('analysis_tasks', 'U') IS NULL
BEGIN
    CREATE TABLE analysis_tasks (
        id INT IDENTITY(1,1) PRIMARY KEY,
        user_id BIGINT NOT NULL,
        status NVARCHAR(50) DEFAULT 'processing',
        md1 NVARCHAR(MAX) NULL, 
        md2 NVARCHAR(MAX) NULL, 
        md3 NVARCHAR(MAX) NULL, 
        md4 NVARCHAR(MAX) NULL, 
        final_report NVARCHAR(MAX) NULL,
        created_at DATETIME DEFAULT GETDATE()
    );
END

USE AgentBotDB;
GO

/*
-- (На випадок якщо щось пішло не так) Видаляємо таблиці, щоб створити їх з чистого листа (УВАГА: дані видаляться)
IF OBJECT_ID('production_rates', 'U') IS NOT NULL DROP TABLE production_rates;
IF OBJECT_ID('specifications', 'U') IS NOT NULL DROP TABLE specifications;
IF OBJECT_ID('inventory_semi', 'U') IS NOT NULL DROP TABLE inventory_semi;
IF OBJECT_ID('inventory_raw', 'U') IS NOT NULL DROP TABLE inventory_raw;
GO
*/

-- 1. Залишки сировини
IF OBJECT_ID('inventory_raw', 'U') IS NULL
BEGIN
CREATE TABLE inventory_raw (
    id INT IDENTITY(1,1) PRIMARY KEY,
    location NVARCHAR(255),
    name NVARCHAR(255),
    unit NVARCHAR(50),
    quantity DECIMAL(15, 3),
    created_at DATETIME DEFAULT GETDATE()
);
END

-- 2. Залишки напівфабрикатів
IF OBJECT_ID('inventory_semi', 'U') IS NULL
BEGIN
CREATE TABLE inventory_semi (
    id INT IDENTITY(1,1) PRIMARY KEY,
    location NVARCHAR(255),
    name NVARCHAR(255),
    unit NVARCHAR(50),
    quantity DECIMAL(15, 3),
    updated_at DATETIME DEFAULT GETDATE()
);
END

-- 3. Специфікації
IF OBJECT_ID('specifications', 'U') IS NULL
BEGIN
CREATE TABLE specifications (
    id INT IDENTITY(1,1) PRIMARY KEY,
    parent_product NVARCHAR(255),
    ingredient NVARCHAR(255),
    norm DECIMAL(15, 5),
    created_at DATETIME DEFAULT GETDATE()
);
END

-- 4. Продуктивність
IF OBJECT_ID('production_rates', 'U') IS NULL
BEGIN
CREATE TABLE production_rates (
    id INT IDENTITY(1,1) PRIMARY KEY,
    op_order INT,
    op_name NVARCHAR(255),
    input_item NVARCHAR(255) NULL,
    output_item NVARCHAR(255),
    rate DECIMAL(15, 3),
    created_at DATETIME DEFAULT GETDATE()
);
END
GO


/* тестування створеної бд
SELECT TABLE_NAME FROM INFORMATION_SCHEMA.TABLES;

USE AgentBotDB;
GO

SELECT 'inventory_raw' as [Table], COUNT(*) as [Count] FROM inventory_raw
UNION ALL
SELECT 'inventory_semi', COUNT(*) FROM inventory_semi
UNION ALL
SELECT 'specifications', COUNT(*) FROM specifications
UNION ALL
SELECT 'production_rates', COUNT(*) FROM production_rates
UNION ALL
SELECT 'analysis_tasks', COUNT(*) FROM analysis_tasks;

SELECT * FROM production_rates;
SELECT * FROM specifications;
SELECT * FROM inventory_semi;
SELECT * FROM inventory_raw;
SELECT * FROM analysis_tasks;
*/