# -*- coding: utf-8 -*-
from odoo import fields, models


class ForsahCategory(models.Model):
    """Opportunity category, lazily upserted from each opportunity's own
    categories[] array (there is no public /categories endpoint - it 401s -
    so this list grows organically as real opportunities are synced).
    """
    _name = 'forsah.category'
    _description = 'Forsah Opportunity Category'
    _order = 'name'

    name = fields.Char(required=True, translate=True)
    ext_id = fields.Char(string='Forsah Category ID', index=True, required=True)
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ('ext_id_uniq', 'unique(ext_id)', 'A category with this Forsah ID already exists.'),
    ]
