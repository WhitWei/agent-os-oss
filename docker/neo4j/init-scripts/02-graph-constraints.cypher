// 02-graph-constraints.cypher
// Domain model constraints for IT Asset Management ontology
// These create the base graph structure before RDF ontology import.

// ── Department uniqueness ──
CREATE CONSTRAINT department_name_unique IF NOT EXISTS
FOR (d:Department) REQUIRE d.name IS UNIQUE;

// ── Employee uniqueness ──
CREATE CONSTRAINT employee_id_unique IF NOT EXISTS
FOR (e:Employee) REQUIRE e.employeeId IS UNIQUE;

// ── Hardware Asset uniqueness (serial number) ──
CREATE CONSTRAINT asset_serial_unique IF NOT EXISTS
FOR (a:HardwareAsset) REQUIRE a.serialNumber IS UNIQUE;

// ── Software Asset uniqueness (license key) ──
CREATE CONSTRAINT software_license_unique IF NOT EXISTS
FOR (s:SoftwareAsset) REQUIRE s.licenseKey IS UNIQUE;

// ── Vendor uniqueness ──
CREATE CONSTRAINT vendor_name_unique IF NOT EXISTS
FOR (v:Vendor) REQUIRE v.name IS UNIQUE;
