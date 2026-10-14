"""Read-only mappings of the schema's views (docs/schema/01_schema_rebased.sql, section 5).

They sit on their OWN ``MetaData``, never ``db.Model``'s: everything that walks
``db.metadata`` - ``tests/char_factories.truncate_all``'s TRUNCATE, ``create_all``, the schema
audit - treats what it finds as a table, and a view is not one. Query them through
``db.session`` like any model; nothing here ever inserts or updates.

* ``EntitySetupSummary`` - one row per company: Xero, modules, how many of the six petty-cash
  accounts and three contacts are mapped (and their names), bill account codes, the opening
  balance. Only the columns the code reads are mapped.
"""
from sqlalchemy import BigInteger, Boolean, Column, Date, Integer, MetaData, String
from sqlalchemy.orm import declarative_base

from blueprints.shared.column_types import MintyUuid, Money
from blueprints.shared.schema import SCHEMA

ViewBase = declarative_base(metadata=MetaData())


#: The six petty-cash account slots and three contact slots, as (view column, label), in the
#: order the dashboard's "Setup Required" list shows a slot left empty. The discrepancy bank
#: account was missing from that list until 2026-10-13, so a company lacking only it saw the
#: dialog with nothing named.
PETTYCASH_SLOTS = (
    ("pettycash_account_name", "Main Bank Account"),
    ("bank_account_name", "Deposit Bank Account"),
    ("cash_sale_account_name", "Cash Sale Account"),
    ("cash_sale_contact_name", "Cash Sale Contact"),
    ("director_account_name", "Owners Account"),
    ("director_contact_name", "Owners Contact"),
    ("discrepancy_account_name", "Discrepancy Account"),
    ("discrepancy_bank_account_name", "Discrepancy Bank Account"),
    ("discrepancy_contact_name", "Discrepancy Contact"),
)


class EntitySetupSummary(ViewBase):
    __tablename__ = "entity_setup_summary"
    __table_args__ = {"schema": SCHEMA, "info": {"is_view": True}}

    entity_id = Column(MintyUuid(), primary_key=True)
    xero_connected = Column(Boolean)
    xero_org_linked = Column(Boolean)
    xero_org_id = Column(String(36))
    xero_tenant_name = Column(String(255))
    pettycash_module_enabled = Column(Boolean)
    bill_module_enabled = Column(Boolean)
    pettycash_accounts_set = Column(Integer)
    pettycash_accounts_total = Column(Integer)
    pettycash_contacts_set = Column(Integer)
    pettycash_contacts_total = Column(Integer)
    bill_accounts_set = Column(BigInteger)  # count(*)
    opening_balance = Column(Money())
    start_date = Column(Date)
    pettycash_account_name = Column(String(80))
    bank_account_name = Column(String(80))
    cash_sale_account_name = Column(String(80))
    discrepancy_bank_account_name = Column(String(80))
    director_account_name = Column(String(80))
    discrepancy_account_name = Column(String(80))
    cash_sale_contact_name = Column(String(150))
    director_contact_name = Column(String(150))
    discrepancy_contact_name = Column(String(150))

    @property
    def missing_pettycash_slots(self) -> list[str]:
        """Labels of the account and contact slots not mapped yet, in the dashboard's order."""
        return [label for column, label in PETTYCASH_SLOTS if getattr(self, column) is None]
