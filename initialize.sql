-- Run in SSMS or sqlcmd using a login with CREATE DATABASE permission.
-- Existing databases are not removed or overwritten.
IF DB_ID(N'GiaoGonShipper') IS NULL
BEGIN
    CREATE DATABASE [GiaoGonShipper];
END;
GO
-- Application creates normalized tables through SQLAlchemy on first startup.
