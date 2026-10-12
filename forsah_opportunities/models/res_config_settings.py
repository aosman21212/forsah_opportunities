# -*- coding: utf-8 -*-
from odoo import api, fields, models
from odoo.exceptions import ValidationError

from .forsah_opportunity import API_BASE


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    forsah_api_base = fields.Char(
        string='API Base URL',
        config_parameter='forsah_opportunities.api_base',
        default=API_BASE,
    )
    forsah_page_size = fields.Integer(
        string='Forsah Page Size',
        config_parameter='forsah_opportunities.page_size',
        default=50,
        help='Number of opportunities requested per API call.',
    )
    forsah_cron_pages = fields.Integer(
        string='Forsah Pages per Sync',
        config_parameter='forsah_opportunities.cron_pages',
        default=5,
        help='Maximum number of pages fetched on each scheduled/manual sync run.',
    )
    forsah_category_ids = fields.Many2many(
        'forsah.category', string='Categories to Sync',
        compute='_compute_forsah_category_ids', inverse='_inverse_forsah_category_ids',
        help='Restrict the daily sync to specific categories. Leave empty to fetch all.',
    )

    @api.depends('forsah_api_base')  # dummy dependency: value is read from ir.config_parameter, not a stored field
    def _compute_forsah_category_ids(self):
        icp = self.env['ir.config_parameter'].sudo()
        ext_ids_str = icp.get_param('forsah_opportunities.category_ext_ids', '') or ''
        ext_ids = [x for x in ext_ids_str.split(',') if x]
        categories = self.env['forsah.category'].search([('ext_id', 'in', ext_ids)]) if ext_ids \
            else self.env['forsah.category']
        for record in self:
            record.forsah_category_ids = categories

    def _inverse_forsah_category_ids(self):
        icp = self.env['ir.config_parameter'].sudo()
        for record in self:
            ext_ids = [ext_id for ext_id in record.forsah_category_ids.mapped('ext_id') if ext_id]
            icp.set_param('forsah_opportunities.category_ext_ids', ','.join(ext_ids))

    @api.constrains('forsah_page_size')
    def _check_forsah_page_size(self):
        for record in self:
            if record.forsah_page_size and not (1 <= record.forsah_page_size <= 100):
                raise ValidationError('Forsah page size must be between 1 and 100.')

    def action_forsah_test_connection(self):
        self.ensure_one()
        self.env['ir.config_parameter'].sudo().set_param(
            'forsah_opportunities.api_base', self.forsah_api_base or API_BASE)
        self.env['forsah.opportunity'].test_connection()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Forsah Opportunities',
                'message': 'Connection successful.',
                'type': 'success',
                'sticky': False,
            },
        }
