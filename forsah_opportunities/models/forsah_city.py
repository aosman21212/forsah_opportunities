# -*- coding: utf-8 -*-
from odoo import fields, models


class ForsahCity(models.Model):
    """Delivery city, lazily upserted from each opportunity's own
    deliveryLocations[].city (same rationale as forsah.category).
    """
    _name = 'forsah.city'
    _description = 'Forsah Delivery City'
    _order = 'name'

    name = fields.Char(required=True, translate=True)
    ext_id = fields.Char(string='Forsah City ID', index=True, required=True)
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ('ext_id_uniq', 'unique(ext_id)', 'A city with this Forsah ID already exists.'),
    ]
