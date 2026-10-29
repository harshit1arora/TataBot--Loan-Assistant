"""MockCRM — a stand-in for the CRM system of record.

Kept deliberately small and honest: it is an HTTP service with a stable contract, seeded
from a fixture, holding customer profiles, KYC state and interaction notes. In a real
deployment this is a vendor system (Salesforce, LeadSquared, …) and only the contract here
would survive.
"""
