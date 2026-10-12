-- MySQL >=8.0.16, InnoDB. Run only in the configured NEW procureflow database.
CREATE TABLE departments (
 id BIGINT PRIMARY KEY AUTO_INCREMENT, department_code VARCHAR(32) NOT NULL UNIQUE,
 department_name VARCHAR(100) NOT NULL, status ENUM('ACTIVE','INACTIVE') NOT NULL DEFAULT 'ACTIVE',
 created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;
CREATE TABLE employees (
 id BIGINT PRIMARY KEY AUTO_INCREMENT, employee_no VARCHAR(32) NOT NULL UNIQUE,
 employee_name VARCHAR(100) NOT NULL, department_id BIGINT NOT NULL,
 role VARCHAR(40) NOT NULL, status ENUM('ACTIVE','INACTIVE') NOT NULL DEFAULT 'ACTIVE',
 FOREIGN KEY(department_id) REFERENCES departments(id)
) ENGINE=InnoDB;
CREATE TABLE department_budgets (
 id BIGINT PRIMARY KEY AUTO_INCREMENT, department_id BIGINT NOT NULL, fiscal_year INT NOT NULL,
 total_budget DECIMAL(18,2) NOT NULL, used_budget DECIMAL(18,2) NOT NULL DEFAULT 0,
 reserved_budget DECIMAL(18,2) NOT NULL DEFAULT 0, updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
 UNIQUE KEY uq_department_year(department_id,fiscal_year),
 FOREIGN KEY(department_id) REFERENCES departments(id),
 CHECK(total_budget >= 0 AND used_budget >= 0 AND reserved_budget >= 0 AND total_budget >= used_budget + reserved_budget)
) ENGINE=InnoDB;
CREATE TABLE products (
 id BIGINT PRIMARY KEY AUTO_INCREMENT, product_code VARCHAR(32) NOT NULL UNIQUE,
 product_name VARCHAR(150) NOT NULL, category VARCHAR(40) NOT NULL, specification VARCHAR(255) NOT NULL,
 reference_price DECIMAL(14,2) NOT NULL, status ENUM('ACTIVE','INACTIVE') NOT NULL DEFAULT 'ACTIVE',
 CHECK(reference_price > 0)
) ENGINE=InnoDB;
CREATE TABLE suppliers (
 id BIGINT PRIMARY KEY AUTO_INCREMENT, supplier_code VARCHAR(32) NOT NULL UNIQUE,
 supplier_name VARCHAR(150) NOT NULL, category VARCHAR(40) NOT NULL,
 profile ENUM('A','B','C','D') NOT NULL,
 status ENUM('ACTIVE','SUSPENDED','BLACKLISTED') NOT NULL,
 rating DECIMAL(4,2) NOT NULL, on_time_rate DECIMAL(6,5) NOT NULL, quality_rate DECIMAL(6,5) NOT NULL,
 created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
 CHECK(rating BETWEEN 0 AND 5 AND on_time_rate BETWEEN 0 AND 1 AND quality_rate BETWEEN 0 AND 1)
) ENGINE=InnoDB;
CREATE TABLE supplier_qualifications (
 id BIGINT PRIMARY KEY AUTO_INCREMENT, supplier_id BIGINT NOT NULL,
 qualification_type VARCHAR(50) NOT NULL, certificate_no VARCHAR(64) NOT NULL UNIQUE,
 valid_from DATE NOT NULL, valid_until DATE NOT NULL, status ENUM('ACTIVE','EXPIRED','REVOKED') NOT NULL,
 UNIQUE KEY uq_supplier_qualification(supplier_id,qualification_type),
 FOREIGN KEY(supplier_id) REFERENCES suppliers(id), CHECK(valid_until >= valid_from)
) ENGINE=InnoDB;
CREATE TABLE supplier_quotes (
 id BIGINT PRIMARY KEY AUTO_INCREMENT, supplier_id BIGINT NOT NULL, product_id BIGINT NOT NULL,
 unit_price DECIMAL(14,2) NOT NULL, available_quantity INT NOT NULL, delivery_days INT NOT NULL,
 valid_from DATE NOT NULL, valid_until DATE NOT NULL, status ENUM('ACTIVE','EXPIRED','WITHDRAWN') NOT NULL,
 created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
 FOREIGN KEY(supplier_id) REFERENCES suppliers(id), FOREIGN KEY(product_id) REFERENCES products(id),
 CHECK(unit_price > 0 AND available_quantity >= 0 AND delivery_days BETWEEN 1 AND 365),
 CHECK(valid_until >= valid_from)
) ENGINE=InnoDB;
CREATE TABLE supplier_performance (
 id BIGINT PRIMARY KEY AUTO_INCREMENT, supplier_id BIGINT NOT NULL, period CHAR(7) NOT NULL,
 total_orders INT NOT NULL, on_time_orders INT NOT NULL, delayed_orders INT NOT NULL,
 accepted_orders INT NOT NULL, quality_issue_orders INT NOT NULL,
 average_delivery_days DECIMAL(7,2) NOT NULL, average_price_index DECIMAL(6,3) NOT NULL,
 UNIQUE KEY uq_supplier_period(supplier_id,period), FOREIGN KEY(supplier_id) REFERENCES suppliers(id),
 CHECK(total_orders >= 0 AND on_time_orders >= 0 AND delayed_orders >= 0 AND accepted_orders >= 0 AND quality_issue_orders >= 0),
 CHECK(total_orders = on_time_orders + delayed_orders AND total_orders = accepted_orders + quality_issue_orders),
 CHECK(average_delivery_days > 0 AND average_price_index > 0)
) ENGINE=InnoDB;
CREATE TABLE procurement_rules (
 id BIGINT PRIMARY KEY AUTO_INCREMENT, rule_code VARCHAR(64) NOT NULL UNIQUE,
 rule_name VARCHAR(100) NOT NULL, rule_type VARCHAR(50) NOT NULL, category VARCHAR(40) NULL,
 min_amount DECIMAL(18,2) NOT NULL DEFAULT 0, max_amount DECIMAL(18,2) NULL,
 rule_config_json JSON NOT NULL, priority INT NOT NULL, enabled BOOLEAN NOT NULL DEFAULT TRUE,
 CHECK(min_amount >= 0 AND (max_amount IS NULL OR max_amount > min_amount))
) ENGINE=InnoDB;
CREATE TABLE approval_rules (
 id BIGINT PRIMARY KEY AUTO_INCREMENT, min_amount DECIMAL(18,2) NOT NULL,
 max_amount DECIMAL(18,2) NULL, approval_chain_json JSON NOT NULL, enabled BOOLEAN NOT NULL DEFAULT TRUE,
 UNIQUE KEY uq_approval_min(min_amount),
 CHECK(min_amount >= 0 AND (max_amount IS NULL OR max_amount > min_amount))
) ENGINE=InnoDB;
CREATE TABLE purchase_requests (
 id BIGINT PRIMARY KEY AUTO_INCREMENT, request_no VARCHAR(64) NOT NULL UNIQUE,
 requester_id BIGINT NOT NULL, department_id BIGINT NOT NULL, fiscal_year INT NOT NULL,
 expected_budget DECIMAL(18,2) NOT NULL, required_delivery_date DATE NOT NULL, reason VARCHAR(1000) NOT NULL,
 status ENUM('DRAFT','PENDING_APPROVAL','APPROVED','REJECTED','ORDER_CREATED','CANCELLED') NOT NULL,
 created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
 FOREIGN KEY(requester_id) REFERENCES employees(id), FOREIGN KEY(department_id,fiscal_year) REFERENCES department_budgets(department_id,fiscal_year),
 CHECK(expected_budget > 0)
) ENGINE=InnoDB;
CREATE TABLE purchase_request_items (
 id BIGINT PRIMARY KEY AUTO_INCREMENT, request_id BIGINT NOT NULL, product_id BIGINT NOT NULL,
 quantity INT NOT NULL, max_unit_price DECIMAL(14,2) NOT NULL, max_total_price DECIMAL(18,2) NOT NULL,
 UNIQUE KEY uq_request_product(request_id,product_id),
 FOREIGN KEY(request_id) REFERENCES purchase_requests(id), FOREIGN KEY(product_id) REFERENCES products(id),
 CHECK(quantity > 0 AND max_unit_price > 0 AND max_total_price = quantity * max_unit_price)
) ENGINE=InnoDB;
CREATE TABLE approval_records (
 id BIGINT PRIMARY KEY AUTO_INCREMENT, request_id BIGINT NOT NULL, approver_id BIGINT NOT NULL,
 approval_level INT NOT NULL, decision ENUM('PENDING','APPROVED','REJECTED') NOT NULL,
 comment VARCHAR(1000) NOT NULL, decided_at DATETIME NULL,
 UNIQUE KEY uq_request_level(request_id,approval_level),
 FOREIGN KEY(request_id) REFERENCES purchase_requests(id), FOREIGN KEY(approver_id) REFERENCES employees(id),
 CHECK(approval_level > 0), CHECK((decision='PENDING' AND decided_at IS NULL) OR (decision <> 'PENDING' AND decided_at IS NOT NULL))
) ENGINE=InnoDB;
CREATE TABLE purchase_orders (
 id BIGINT PRIMARY KEY AUTO_INCREMENT, po_no VARCHAR(64) NOT NULL UNIQUE,
 request_id BIGINT NOT NULL UNIQUE, department_id BIGINT NOT NULL, supplier_id BIGINT NOT NULL,
 total_amount DECIMAL(18,2) NOT NULL, status ENUM('CREATED','CONFIRMED','CANCELLED') NOT NULL,
 created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, updated_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
 FOREIGN KEY(request_id) REFERENCES purchase_requests(id), FOREIGN KEY(department_id) REFERENCES departments(id),
 FOREIGN KEY(supplier_id) REFERENCES suppliers(id), CHECK(total_amount > 0)
) ENGINE=InnoDB;
CREATE TABLE purchase_order_items (
 id BIGINT PRIMARY KEY AUTO_INCREMENT, purchase_order_id BIGINT NOT NULL, product_id BIGINT NOT NULL,
 quote_id BIGINT NULL, quantity INT NOT NULL, unit_price DECIMAL(14,2) NOT NULL, total_price DECIMAL(18,2) NOT NULL,
 UNIQUE KEY uq_order_product(purchase_order_id,product_id),
 FOREIGN KEY(purchase_order_id) REFERENCES purchase_orders(id), FOREIGN KEY(product_id) REFERENCES products(id),
 FOREIGN KEY(quote_id) REFERENCES supplier_quotes(id),
 CHECK(quantity > 0 AND unit_price > 0 AND total_price = quantity * unit_price)
) ENGINE=InnoDB;
CREATE TABLE budget_transactions (
 id BIGINT PRIMARY KEY AUTO_INCREMENT, department_id BIGINT NOT NULL, fiscal_year INT NOT NULL,
 request_id BIGINT NULL, transaction_type ENUM('RESERVE','RELEASE','COMMIT','ADJUST') NOT NULL,
 amount DECIMAL(18,2) NOT NULL, balance_after DECIMAL(18,2) NOT NULL,
 transaction_time DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP, description VARCHAR(255) NOT NULL,
 FOREIGN KEY(department_id,fiscal_year) REFERENCES department_budgets(department_id,fiscal_year),
 FOREIGN KEY(request_id) REFERENCES purchase_requests(id),
 CHECK(balance_after >= 0), CHECK((transaction_type='ADJUST' AND amount <> 0) OR (transaction_type <> 'ADJUST' AND amount > 0))
) ENGINE=InnoDB;
