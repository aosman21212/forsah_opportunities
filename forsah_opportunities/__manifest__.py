# -*- coding: utf-8 -*-
{
    'name': 'Forsah Opportunities',
    'version': '17.0.1.0.0',
    'summary': 'Sync Forsah (forsah.sa) RFQ/tender opportunities into Odoo and convert them to CRM opportunities',
    'description': """
Forsah Opportunities
======================
Pulls business opportunities (RFQs / direct-purchase requests) from the
Saudi "Forsah" (فرصة) SME procurement marketplace (forsah.sa) into Odoo and
lets you convert any opportunity into a CRM opportunity in one click.

Technical notes
----------------
Forsah's API (https://forsah-api.910ths.sa/api/v1) is public and requires no
authentication for the listing/detail endpoints used here - confirmed live::

    GET /opportunities?page=&perPage=        (list, paginated)
    GET /opportunities/{id}                  (detail, includes referenceNumber)
    GET /opportunities/count                 (aggregate stats)

Public opportunity page: https://forsah.sa/marketplace/{id}

categoryIds/statusKey query params did not appear to filter server-side when
tested, so category/title filtering in the manual wizard is done client-side
after fetching, same approach as etimad_tenders for its own unconfirmed
filters. Search for "ADJUST" in models/forsah_opportunity.py for anything
still worth re-checking.
""",
    'category': 'Sales/CRM',
    'author': 'leapai.ai',
    'website': 'https://leapai.ai',
    'support': 'sales@leapai.ai',
    'maintainer': 'LEAP AI',
    'depends': ['crm', 'mail'],
    'images': ['static/description/screenshot1.png'],
    'data': [
        'security/forsah_security.xml',
        'security/ir.model.access.csv',
        'data/ir_cron_data.xml',
        'views/forsah_opportunity_views.xml',
        'views/forsah_master_data_views.xml',
        'views/res_config_settings_views.xml',
        'wizard/forsah_fetch_wizard_views.xml',
    ],
    'installable': True,
    'auto_install': False,
    'application': True,
    'license': 'LGPL-3',
}
