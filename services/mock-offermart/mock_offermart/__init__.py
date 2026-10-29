"""OfferMart — a stand-in for the pricing / offer engine.

Owns the product catalogue and the pricing rules, and asks MockCRM for the customer
profile rather than duplicating it. That service-to-service hop is deliberate: it is how
the real pair behaves, and it keeps one system of record per fact.
"""
