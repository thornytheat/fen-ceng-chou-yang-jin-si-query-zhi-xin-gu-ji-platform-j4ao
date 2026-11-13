-- 0002：自检驳回后的「只补未达标层」补样与查询版本化
-- 幂等：可在已执行过 0001 的库上重复执行；全新库由 ORM create_all 兜底，本脚本只做增量变更。
-- 目标库 MySQL 8.0；存储过程用于「列/约束不存在才添加」，避免 IF NOT EXISTS 语法差异。

-- ---------------------------------------------------------------- approx_queries 版本链
DROP PROCEDURE IF EXISTS sampleaqp_add_query_revision_columns;
DELIMITER //
CREATE PROCEDURE sampleaqp_add_query_revision_columns()
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.COLUMNS
                 WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'approx_queries'
                   AND COLUMN_NAME = 'root_query_id') THEN
    ALTER TABLE approx_queries
      ADD COLUMN root_query_id BIGINT NULL AFTER code,
      ADD COLUMN revision_no INT NOT NULL DEFAULT 1 AFTER root_query_id,
      ADD COLUMN superseded_by_id BIGINT NULL AFTER revision_no,
      ADD COLUMN is_latest TINYINT(1) NOT NULL DEFAULT 1 AFTER superseded_by_id,
      ADD INDEX ix_query_root (root_query_id),
      ADD INDEX ix_query_latest (is_latest),
      ADD CONSTRAINT fk_query_root FOREIGN KEY (root_query_id)
        REFERENCES approx_queries(id) ON DELETE CASCADE,
      ADD CONSTRAINT fk_query_superseded FOREIGN KEY (superseded_by_id)
        REFERENCES approx_queries(id) ON DELETE SET NULL;
  END IF;
END //
DELIMITER ;
CALL sampleaqp_add_query_revision_columns();
DROP PROCEDURE IF EXISTS sampleaqp_add_query_revision_columns;

-- 存量行初始化为根版本 v1、最新版本
UPDATE approx_queries
SET root_query_id = id, revision_no = 1, is_latest = 1
WHERE root_query_id IS NULL;

-- 同一根查询下版本号唯一（NULL 不参与唯一性，存量行已全部回填 root_query_id）
DROP PROCEDURE IF EXISTS sampleaqp_add_query_revision_uq;
DELIMITER //
CREATE PROCEDURE sampleaqp_add_query_revision_uq()
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.TABLE_CONSTRAINTS
                 WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'approx_queries'
                   AND CONSTRAINT_NAME = 'uq_query_revision') THEN
    ALTER TABLE approx_queries ADD CONSTRAINT uq_query_revision UNIQUE (root_query_id, revision_no);
  END IF;
END //
DELIMITER ;
CALL sampleaqp_add_query_revision_uq();
DROP PROCEDURE IF EXISTS sampleaqp_add_query_revision_uq;

-- ---------------------------------------------------------------- qc_checks 版本化
DROP PROCEDURE IF EXISTS sampleaqp_add_qc_revision_columns;
DELIMITER //
CREATE PROCEDURE sampleaqp_add_qc_revision_columns()
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.COLUMNS
                 WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'qc_checks'
                   AND COLUMN_NAME = 'revision_no') THEN
    ALTER TABLE qc_checks ADD COLUMN revision_no INT NOT NULL DEFAULT 1 AFTER code;
  END IF;
END //
DELIMITER ;
CALL sampleaqp_add_qc_revision_columns();
DROP PROCEDURE IF EXISTS sampleaqp_add_qc_revision_columns;

-- code 列从唯一降为普通列：每个查询版本各自一条 QC，code 允许按版本重复（QC-{queryCode}-r{n}）
DROP PROCEDURE IF EXISTS sampleaqp_drop_qc_code_uq;
DELIMITER //
CREATE PROCEDURE sampleaqp_drop_qc_code_uq()
BEGIN
  IF EXISTS (SELECT 1 FROM information_schema.STATISTICS
             WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'qc_checks'
               AND INDEX_NAME = 'code' AND NON_UNIQUE = 0) THEN
    ALTER TABLE qc_checks DROP INDEX code;
  END IF;
END //
DELIMITER ;
CALL sampleaqp_drop_qc_code_uq();
DROP PROCEDURE IF EXISTS sampleaqp_drop_qc_code_uq;

-- 与 ORM create_all 对齐：code 保留普通索引（不再唯一）
DROP PROCEDURE IF EXISTS sampleaqp_add_qc_code_idx;
DELIMITER //
CREATE PROCEDURE sampleaqp_add_qc_code_idx()
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.STATISTICS
                 WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'qc_checks'
                   AND INDEX_NAME = 'ix_qc_code') THEN
    CREATE INDEX ix_qc_code ON qc_checks (code);
  END IF;
END //
DELIMITER ;
CALL sampleaqp_add_qc_code_idx();
DROP PROCEDURE IF EXISTS sampleaqp_add_qc_code_idx;

DROP PROCEDURE IF EXISTS sampleaqp_add_qc_revision_uq;
DELIMITER //
CREATE PROCEDURE sampleaqp_add_qc_revision_uq()
BEGIN
  IF NOT EXISTS (SELECT 1 FROM information_schema.TABLE_CONSTRAINTS
                 WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'qc_checks'
                   AND CONSTRAINT_NAME = 'uq_qc_query_revision') THEN
    ALTER TABLE qc_checks ADD CONSTRAINT uq_qc_query_revision UNIQUE (query_id, revision_no);
  END IF;
END //
DELIMITER ;
CALL sampleaqp_add_qc_revision_uq();
DROP PROCEDURE IF EXISTS sampleaqp_add_qc_revision_uq;

-- ---------------------------------------------------------------- 补样单
CREATE TABLE IF NOT EXISTS sample_topups (
  id BIGINT PRIMARY KEY AUTO_INCREMENT,
  query_id BIGINT NOT NULL,
  new_query_id BIGINT NULL,
  idempotency_key VARCHAR(160) NOT NULL,
  status VARCHAR(16) NOT NULL,
  plan JSON NOT NULL,
  applied JSON NOT NULL,
  reject_reason VARCHAR(400) NULL,
  attempt_count INT NOT NULL DEFAULT 0,
  created_by VARCHAR(160) NOT NULL,
  created_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3),
  updated_at DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3),
  UNIQUE KEY uq_topup_idempotency (idempotency_key),
  KEY ix_topup_query (query_id),
  CONSTRAINT fk_topup_query FOREIGN KEY (query_id) REFERENCES approx_queries(id) ON DELETE CASCADE,
  CONSTRAINT fk_topup_new_query FOREIGN KEY (new_query_id) REFERENCES approx_queries(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
