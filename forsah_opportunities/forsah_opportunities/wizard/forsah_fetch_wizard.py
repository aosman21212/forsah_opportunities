# -*- coding: utf-8 -*-
from odoo import fields, models


class ForsahFetchWizard(models.TransientModel):
    _name = 'forsah.fetch.wizard'
    _description = 'Fetch Forsah Opportunities Now'

    max_pages = fields.Integer(
        string='Pages to Fetch', default=1,
        help='How many pages to pull per category in this manual run '
             '(overrides the Settings default for this run only).',
    )
    page_size = fields.Integer(
        string='Page Size', default=50,
        help='Number of opportunities requested per page (API default page size is small, so raise this '
             'for a meaningful manual pull).',
    )
    category_ids = fields.Many2many(
        'forsah.category', string='Categories',
        help='Restrict this run to specific categories. Leave empty to fetch all.',
    )
    title_contains = fields.Char(string='Title Contains')

    def action_fetch_now(self):
        self.ensure_one()
        Opportunity = self.env['forsah.opportunity']
        ext_ids = [ext_id for ext_id in self.category_ids.mapped('ext_id') if ext_id]
        kwargs = {
            'pages': self.max_pages or 1,
            'page_size': self.page_size or 50,
            'title_filter': self.title_contains or None,
        }

        if ext_ids:
            total = {'created': 0, 'updated': 0, 'errors': []}
            for ext_id in ext_ids:
                result = Opportunity.fetch_opportunities(category_ext_id=ext_id, **kwargs)
                total['created'] += result['created']
                total['updated'] += result['updated']
                total['errors'].extend(result['errors'])
        else:
            total = Opportunity.fetch_opportunities(**kwargs)

        message = 'Sync finished: %s created, %s updated, %s error(s).' % (
            total['created'], total['updated'], len(total['errors']))
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Forsah Opportunities',
                'message': message,
                'type': 'warning' if total['errors'] else 'success',
                'sticky': True,
            },
        }
