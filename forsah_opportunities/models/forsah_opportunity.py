# -*- coding: utf-8 -*-
"""
HTTP client for the Forsah (forsah.sa) opportunities marketplace.

CONFIRMED live against this container (2026-10-12), fully public, no
authentication required for these three endpoints:
    GET https://forsah-api.910ths.sa/api/v1/opportunities?page=&perPage=
        -> {"pagination": {"page","perPage","pageCount","totalCount"}, "result": [...]}
    GET https://forsah-api.910ths.sa/api/v1/opportunities/{id}
        -> same shape as one list item, PLUS "referenceNumber" (not present in the list)
    GET https://forsah-api.910ths.sa/api/v1/opportunities/count
        -> {"count", "totalAwardedValue", "totalPublishedValue"}
Public opportunity page (for the "View on Forsah" link): https://forsah.sa/marketplace/{id}

categoryIds=<uuid> and statusKey=open query params did NOT appear to narrow
the result set when tested directly, so wizard-level category/title
filtering is done client-side after fetching - ADJUST _call_api if a real
server-side filter param name is confirmed later.
"""
import logging
import re

import requests

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

API_BASE = 'https://forsah-api.910ths.sa/api/v1'
OPPORTUNITIES_ENDPOINT = API_BASE + '/opportunities'
PUBLIC_URL_TEMPLATE = 'https://forsah.sa/marketplace/%s'

DEFAULT_USER_AGENT = (
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
    '(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36'
)
REQUEST_TIMEOUT = 30


class ForsahOpportunity(models.Model):
    _name = 'forsah.opportunity'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _description = 'Forsah Opportunity'
    _order = 'due_date desc, id desc'
    _rec_name = 'name'

    name = fields.Char(string='Title', required=True, tracking=True)
    opportunity_id_external = fields.Char(
        string='Forsah ID', required=True, index=True, tracking=True,
        help='Unique opportunity UUID on the Forsah platform, used to avoid duplicates on sync.',
    )
    reference = fields.Char(
        string='Reference Number', tracking=True,
        help='Only available after a detail fetch - the list endpoint does not include it.',
    )
    type_key = fields.Char(string='Type Key')
    type_name = fields.Char(string='Type')
    status_key = fields.Char(string='Status Key', tracking=True)
    category_ids = fields.Many2many('forsah.category', string='Categories')
    city_ids = fields.Many2many('forsah.city', string='Delivery Cities')
    publisher_type = fields.Char(string='Publisher Type')

    value_range_name = fields.Char(string='Value Range')
    value_min = fields.Monetary(string='Value Min', currency_field='currency_id')
    value_max = fields.Monetary(string='Value Max', currency_field='currency_id', tracking=True)
    currency_id = fields.Many2one(
        'res.currency', string='Currency',
        default=lambda self: self.env.ref('base.SAR', raise_if_not_found=False)
        or self.env.company.currency_id,
    )

    publish_date = fields.Date(string='Publication Date')
    due_date = fields.Datetime(string='Due Date', tracking=True)
    extended_due_date = fields.Datetime(string='Extended Due Date')
    close_date = fields.Datetime(string='Close Date')
    award_date = fields.Datetime(string='Award Date')
    days_to_go = fields.Integer(string='Days to Go')

    bids_count = fields.Integer(string='Bids')
    submitted_bids_count = fields.Integer(string='Submitted Bids')
    view_count = fields.Integer(string='Views')
    accepts_more_bids = fields.Boolean(string='Accepts More Bids')

    opportunity_url = fields.Char(string='Link on Forsah')
    state = fields.Selection([
        ('new', 'New'),
        ('in_progress', 'In Progress'),
        ('converted', 'Converted to Opportunity'),
        ('closed', 'Closed'),
    ], string='Status', default='new', tracking=True)
    crm_lead_id = fields.Many2one('crm.lead', string='CRM Opportunity', readonly=True, copy=False)
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company)
    active = fields.Boolean(default=True)
    raw_data = fields.Text(string='Last Raw API Payload', readonly=True, copy=False)
    last_synced_at = fields.Datetime(string='Last Synced', readonly=True, copy=False)

    _sql_constraints = [
        ('opportunity_id_external_company_uniq', 'unique(opportunity_id_external, company_id)',
         'An opportunity with this Forsah ID already exists for this company.'),
    ]

    # ------------------------------------------------------------------
    # CRM conversion
    # ------------------------------------------------------------------
    def action_convert_to_opportunity(self):
        self.ensure_one()
        if self.crm_lead_id:
            return self._open_crm_lead_action()
        lead = self.env['crm.lead'].create({
            'name': self.name or self.reference or self.opportunity_id_external,
            'type': 'opportunity',
            'expected_revenue': self.value_max or self.value_min,
            'date_deadline': self.due_date and fields.Datetime.to_datetime(self.due_date).date(),
            'description': _(
                'Imported from Forsah opportunity %(ref)s.\nLink: %(url)s'
            ) % {
                'ref': self.reference or self.opportunity_id_external,
                'url': self.opportunity_url or '',
            },
        })
        self.write({'crm_lead_id': lead.id, 'state': 'converted'})
        self.message_post(body=_('Converted to opportunity %s.') % lead.name)
        return self._open_crm_lead_action()

    def _open_crm_lead_action(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'crm.lead',
            'view_mode': 'form',
            'res_id': self.crm_lead_id.id,
            'target': 'current',
        }

    def action_open_on_forsah(self):
        self.ensure_one()
        if not self.opportunity_url:
            raise UserError(_('This opportunity has no Forsah link.'))
        return {
            'type': 'ir.actions.act_url',
            'url': self.opportunity_url,
            'target': 'new',
        }

    def action_fetch_detail(self):
        """Fetch the single-opportunity detail endpoint for this record,
        to pick up the reference number (not present in the list payload).
        """
        self.ensure_one()
        session = self._get_http_session()
        try:
            response = session.get(
                '%s/%s' % (OPPORTUNITIES_ENDPOINT, self.opportunity_id_external),
                timeout=REQUEST_TIMEOUT,
            )
            response.raise_for_status()
            rec = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise UserError(_('Could not fetch detail from Forsah: %s') % exc)

        # IMPORTANT: the detail endpoint's payload is NOT a superset of the list
        # endpoint's - notably its valueRange only has {name, key}, no min/max.
        # Blindly writing _prepare_vals_from_api(rec) here would clobber the
        # richer data already captured from the list sync with zeros/blanks, so
        # only merge in values that are actually present, keeping the rest.
        vals = self._prepare_vals_from_api(rec)
        vals = {key: value for key, value in vals.items() if value not in (False, None, 0, 0.0, [])}
        # category_ids/city_ids are always present as (6, 0, [...]) commands, even
        # when empty - re-check those explicitly so an empty detail list doesn't wipe
        # out categories/cities already known from the list sync.
        for m2m_field in ('category_ids', 'city_ids'):
            command = vals.get(m2m_field)
            if command and not command[0][2]:
                vals.pop(m2m_field)
        self.write(vals)
        return True

    # ------------------------------------------------------------------
    # HTTP client / sync
    # ------------------------------------------------------------------
    def _get_sync_params(self):
        icp = self.env['ir.config_parameter'].sudo()
        ext_ids_str = icp.get_param('forsah_opportunities.category_ext_ids', '') or ''
        return {
            'api_base': icp.get_param('forsah_opportunities.api_base', API_BASE) or API_BASE,
            'page_size': int(icp.get_param('forsah_opportunities.page_size', 50) or 50),
            'cron_pages': int(icp.get_param('forsah_opportunities.cron_pages', 5) or 5),
            'category_ext_ids': [x for x in ext_ids_str.split(',') if x],
        }

    def _get_http_session(self):
        session = requests.Session()
        session.headers.update({
            'User-Agent': DEFAULT_USER_AGENT,
            'Accept': 'application/json',
        })
        return session

    def test_connection(self):
        """Used by the Settings 'Test Connection' button."""
        params = self._get_sync_params()
        session = self._get_http_session()
        endpoint = params['api_base'].rstrip('/') + '/opportunities'
        try:
            response = session.get(endpoint, params={'page': 1, 'perPage': 1}, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            response.json()
        except (requests.RequestException, ValueError) as exc:
            raise UserError(_('Connection to Forsah failed: %s') % exc)
        return True

    def _call_api(self, session, endpoint, page_number, page_size, category_ext_id=None):
        query_params = {'page': page_number, 'perPage': page_size}
        if category_ext_id:
            query_params['categoryIds'] = category_ext_id  # ADJUST: unconfirmed as an actual server-side filter
        response = session.get(endpoint, params=query_params, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        payload = response.json()
        return payload.get('result', []) if isinstance(payload, dict) else []

    @staticmethod
    def _coalesce(rec, *keys):
        for key in keys:
            value = rec.get(key)
            if value not in (None, ''):
                return value
        return False

    @staticmethod
    def _parse_datetime(value):
        """Tolerant parse of the API's datetime strings (seen as plain
        "YYYY-MM-DD HH:MM:SS", but handled defensively in case an ISO "T"
        variant shows up on some field/endpoint) into Odoo's format.
        """
        if not value or not isinstance(value, str):
            return False
        value = value.strip().replace('T', ' ')
        value = value.split('.')[0]
        value = re.sub(r'[+-]\d{2}:\d{2}$', '', value)
        return value[:19] or False

    def _get_or_create_categories(self, categories):
        Category = self.env['forsah.category']
        ids = []
        for cat in categories or []:
            ext_id = cat.get('id')
            if not ext_id:
                continue
            name = (cat.get('name') or {}).get('en') or (cat.get('name') or {}).get('ar') or ext_id
            category = Category.search([('ext_id', '=', ext_id)], limit=1)
            if not category:
                category = Category.create({'ext_id': ext_id, 'name': name})
            ids.append(category.id)
        return ids

    def _get_or_create_cities(self, delivery_locations):
        City = self.env['forsah.city']
        ids = []
        for loc in delivery_locations or []:
            city = (loc or {}).get('city') or {}
            ext_id = city.get('key') or city.get('id')
            if not ext_id:
                continue
            name = (city.get('name') or {}).get('en') or (city.get('name') or {}).get('ar') or ext_id
            rec = City.search([('ext_id', '=', ext_id)], limit=1)
            if not rec:
                rec = City.create({'ext_id': ext_id, 'name': name})
            ids.append(rec.id)
        return ids

    def _prepare_vals_from_api(self, rec):
        value_range = rec.get('valueRange') or {}
        type_info = rec.get('type') or {}
        type_name = (type_info.get('name') or {}).get('en') or (type_info.get('name') or {}).get('ar')

        return {
            'opportunity_id_external': rec.get('id'),
            'name': self._coalesce(rec, 'title') or rec.get('id'),
            'reference': self._coalesce(rec, 'referenceNumber'),
            'type_key': type_info.get('key'),
            'type_name': type_name,
            'status_key': rec.get('statusKey'),
            'category_ids': [(6, 0, self._get_or_create_categories(rec.get('categories')))],
            'city_ids': [(6, 0, self._get_or_create_cities(rec.get('deliveryLocations')))],
            'publisher_type': ((rec.get('publisher') or {}).get('publisherType')),
            'value_range_name': (value_range.get('name') or {}).get('en') or (value_range.get('name') or {}).get('ar'),
            'value_min': value_range.get('min') or 0.0,
            'value_max': value_range.get('max') or 0.0,
            'publish_date': rec.get('publishDate') or False,
            'due_date': self._parse_datetime(rec.get('dueDate')),
            'extended_due_date': self._parse_datetime(rec.get('extendedDueDate')),
            'close_date': self._parse_datetime(rec.get('closeDate')),
            'award_date': self._parse_datetime(rec.get('awardDate')),
            'days_to_go': rec.get('daysToGo') or 0,
            'bids_count': rec.get('bidsCount') or 0,
            'submitted_bids_count': rec.get('submittedBidsCount') or 0,
            'view_count': rec.get('viewCount') or 0,
            'accepts_more_bids': bool(rec.get('acceptsMoreBids')),
            'opportunity_url': PUBLIC_URL_TEMPLATE % rec['id'] if rec.get('id') else False,
            'raw_data': str(rec),
            'last_synced_at': fields.Datetime.now(),
        }

    def _upsert_vals(self, vals):
        if not vals.get('opportunity_id_external'):
            _logger.warning('Forsah Opportunities: skipping record with no identifiable id: %s', str(vals)[:300])
            return False, False
        existing = self.search([
            ('opportunity_id_external', '=', vals['opportunity_id_external']),
            ('company_id', '=', self.env.company.id),
        ], limit=1)
        if existing:
            existing.write(vals)
            return existing, 'updated'
        vals['company_id'] = self.env.company.id
        created = self.create(vals)
        return created, 'created'

    def fetch_opportunities(self, pages=None, page_size=None, category_ext_id=None,
                             title_filter=None, category_filter=None):
        """Fetch opportunities page by page and upsert them. Optional
        client-side filters (title/category substring match) are applied
        after mapping, since server-side filter support is unconfirmed.
        Returns {'created': int, 'updated': int, 'errors': [str, ...]}.
        """
        params = self._get_sync_params()
        page_size = page_size or params['page_size']
        pages = pages or params['cron_pages']
        endpoint = params['api_base'].rstrip('/') + '/opportunities'
        session = self._get_http_session()

        total = {'created': 0, 'updated': 0, 'errors': []}
        for page_number in range(1, pages + 1):
            try:
                records = self._call_api(session, endpoint, page_number, page_size, category_ext_id=category_ext_id)
            except (requests.RequestException, ValueError) as exc:
                msg = 'fetch failed on page %s%s: %s' % (
                    page_number, (' (category %s)' % category_ext_id) if category_ext_id else '', exc)
                _logger.warning('Forsah Opportunities: %s', msg)
                total['errors'].append(msg)
                break
            if not records:
                break
            for rec in records:
                try:
                    vals = self._prepare_vals_from_api(rec)
                except Exception as exc:  # noqa: BLE001
                    msg = 'failed to map record %s: %s' % (str(rec)[:120], exc)
                    _logger.exception('Forsah Opportunities: %s', msg)
                    total['errors'].append(msg)
                    continue
                if title_filter and title_filter.lower() not in (vals.get('name') or '').lower():
                    continue
                if category_filter:
                    cat_names = [c.get('name', {}).get('en', '') + c.get('name', {}).get('ar', '')
                                 for c in (rec.get('categories') or [])]
                    if not any(category_filter.lower() in n.lower() for n in cat_names):
                        continue
                try:
                    _record, action = self._upsert_vals(vals)
                except Exception as exc:  # noqa: BLE001
                    msg = 'failed to upsert record %s: %s' % (str(vals)[:120], exc)
                    _logger.exception('Forsah Opportunities: %s', msg)
                    total['errors'].append(msg)
                    continue
                if action == 'created':
                    total['created'] += 1
                elif action == 'updated':
                    total['updated'] += 1

            if len(records) < page_size:
                break
        return total

    def action_scheduled_fetch(self):
        try:
            params = self._get_sync_params()
            ext_ids = params['category_ext_ids']
            pages = params['cron_pages']
            if ext_ids:
                total = {'created': 0, 'updated': 0, 'errors': []}
                for ext_id in ext_ids:
                    result = self.fetch_opportunities(pages=pages, category_ext_id=ext_id)
                    total['created'] += result['created']
                    total['updated'] += result['updated']
                    total['errors'].extend(result['errors'])
                _logger.info(
                    'Forsah scheduled fetch (%d categories) complete: %s',
                    len(ext_ids), total
                )
            else:
                result = self.fetch_opportunities(pages=pages)
                _logger.info(
                    'Forsah scheduled fetch (all categories) complete: %s', result
                )
        except Exception:  # noqa: BLE001 - a cron must never hard-crash the scheduler
            _logger.exception('Forsah Opportunities: scheduled fetch failed')
