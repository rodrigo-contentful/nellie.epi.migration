"""

This script imports voyages from Episerver to Contentful if they already are not added
to Contentful. This is checked by Contentful entry ID. For imported voyages it is the
same as entry id in Epi. To update voyages they first need to be deleted from Contentful
and then imported from Episerver by this script. When adding voyage, entries and assets
that has been previously linked to the old imported voyage and thus have the same id are
deleted and re-imported.

"""

import config
import helpers
import logging
from argparse import ArgumentParser

logging.basicConfig(
    format = '%(asctime)s %(levelname)-8s %(message)s',
    level = logging.INFO,
    datefmt = '%Y-%m-%d %H:%M:%S')

CMS_API_URLS = {
    "en": "https://global.hurtigruten.com/rest/b2b/voyages",
    "EN-AMERICAS": "https://www.hurtigruten.com/rest/b2b/voyages",
    "EN-APAC": "https://www.hurtigruten.com.au/rest/b2b/voyages"
}


def prepare_environment():
    logging.info('Setup Contentful environment')
    contentful_environment = helpers.create_contentful_environment(
        config.CTFL_SPACE_ID,
        config.CTFL_ENV_ID,
        config.CTFL_MGMT_API_KEY)

    logging.info('Get all voyages for locales: %s' % (", ".join([key for key, value in CMS_API_URLS.items()])))

    voyage_ids = []
    for key, value in CMS_API_URLS.items():
        voyage_ids += [voyage['id'] for voyage in helpers.read_json_data(value)]

    # Create distinct list
    voyage_ids = set(voyage_ids)

    logging.info('Number of voyages in EPI: %s' % len(voyage_ids))
    logging.info('')
    logging.info('-----------------------------------------------------')
    logging.info('Voyage IDs to migrate: ')
    for voyage_id in voyage_ids:
        logging.info(voyage_id)
    logging.info('-----------------------------------------------------')
    logging.info('')

    return voyage_ids, contentful_environment


def update_voyage(contentful_environment, voyage_id):
    logging.info('Voyage migration started with ID: %s' % voyage_id)

    voyage_detail_by_locale = {}

    for locale, url in CMS_API_URLS.items():
        # load all fields for the particular voyage by calling GET voyages/{id}
        voyage_detail_by_locale[locale] = helpers.read_json_data("%s/%s" % (url, voyage_id))

    default_voyage_detail = voyage_detail_by_locale[config.DEFAULT_LOCALE]

    if default_voyage_detail is None:
        logging.info('Could not find default voyage detail for voyage ID: %s' % voyage_id)
        return

    # Assuming that number of selling points is the same for every locale
    usps = [
        helpers.add_entry(
            environment = contentful_environment,
            id = "usp%s-%d" % (voyage_id, i),
            content_type_id = "usp",
            fields = helpers.merge_localized_dictionaries(*(
                helpers.field_localizer(
                    locale, {'text': locale_voyage_detail['sellingPoints'][i]}
                )
                for locale, locale_voyage_detail in voyage_detail_by_locale.items()
            ))
        ) for i, usp in enumerate(default_voyage_detail['sellingPoints'])
    ]

    # Assuming that media is same for every locale
    media = [
        helpers.add_asset(
            environment = contentful_environment,
            asset_uri = media_item['highResolutionUri'],
            id = "voyagePicture%s-%d" % (voyage_id, i),
            title = media_item['alternateText']
        ) for i, media_item in enumerate(default_voyage_detail['mediaContent'])
    ]

    # Assuming that itinerary days are the same for every locale
    itinerary = [
        helpers.add_entry(
            environment = contentful_environment,
            id = "itday%s-%d" % (voyage_id, i),
            content_type_id = "itineraryDay",
            fields = helpers.merge_localized_dictionaries(*(
                helpers.field_localizer(locale, {
                    'day': locale_voyage_detail['itinerary'][i]['day'],
                    'location': locale_voyage_detail['itinerary'][i]['location'],
                    'name': locale_voyage_detail['itinerary'][i]['heading'],
                    'description': helpers.convert_to_contentful_rich_text(
                        locale_voyage_detail['itinerary'][i]['body']
                    ),
                    'images': [
                        helpers.add_asset(
                            environment = contentful_environment,
                            asset_uri = media_item['highResolutionUri'],
                            id = "itdpic%d-%s-%d" % (
                                locale_voyage_detail['id'],
                                helpers.camelize(locale_voyage_detail['itinerary'][i]['day']),
                                k),
                            title = media_item['alternateText']
                        ) for k, media_item in enumerate(locale_voyage_detail['itinerary'][i]['mediaContent'])
                    ]
                }) for locale, locale_voyage_detail in voyage_detail_by_locale.items()
            ))
        ) for i, itinerary_day in enumerate(default_voyage_detail['itinerary'])
    ]

    helpers.add_entry(
        environment = contentful_environment,
        id = str(voyage_id),
        content_type_id = "voyage",
        fields = helpers.merge_localized_dictionaries(*(
            helpers.field_localizer(locale, {
                'name': voyage_detail['heading'],
                'description': voyage_detail['intro'],
                'included': helpers.convert_to_contentful_rich_text(voyage_detail['includedInfo']),
                'notIncluded': helpers.convert_to_contentful_rich_text(voyage_detail['notIncludedInfo']),
                'travelSuggestionCodes': voyage_detail['travelSuggestionCodes'],
                'duration': voyage_detail['durationText'],
                'destinations': [helpers.entry_link(voyage_detail['destinationId'])],
                'fromPort': helpers.entry_link(voyage_detail['fromPort']),
                'toPort': helpers.entry_link(voyage_detail['toPort']),
                'notes': helpers.convert_to_contentful_rich_text(voyage_detail['notes']),
                'usps': usps,
                'map': helpers.add_asset(  # assuming map can be different for different locales
                    environment = contentful_environment,
                    asset_uri = voyage_detail['largeMap']['highResolutionUri'],
                    id = "voyageMap%d-%s" % (voyage_id, locale),
                    title = voyage_detail['largeMap']['alternateText'],
                    file_name = voyage_detail['largeMap']['alternateText']
                ),
                'media': media,
                'itinerary': itinerary
            }) for locale, voyage_detail in voyage_detail_by_locale.items()
        ))
    )

    logging.info('Voyage migration finished with ID: %s' % voyage_id)


def run_sync(**kwargs):
    parameter_voyage_ids = kwargs.get('content_ids')
    include = kwargs.get('include')
    if parameter_voyage_ids is not None:
        if include:
            logging.info('Running voyages sync on specified IDs: %s' % parameter_voyage_ids)
        else:
            logging.info('Running voyages sync, skipping IDs: %s' % parameter_voyage_ids)
    else:
        logging.info('Running voyages sync')
    voyage_ids, contentful_environment = prepare_environment()
    for voyage_id in voyage_ids:
        if parameter_voyage_ids is not None:
            # run only included voyages
            if include and voyage_id not in parameter_voyage_ids:
                continue
            # skip excluded voyages
            if not include and voyage_id in parameter_voyage_ids:
                continue
        update_voyage(contentful_environment, voyage_id)


parser = ArgumentParser(prog = 'voyages.py', description = 'Run voyage sync between Contentful and EPI')
parser.add_argument("-ids", "--content_ids", nargs = '+', type = int, help = "Provide voyage IDs")
parser.add_argument("-include", "--include", nargs = '+', type = bool,
                    help = "Specify if you want to include or exclude "
                           "voyage IDs")
args = parser.parse_args()

if __name__ == '__main__':
    ids = vars(args)['content_ids']
    include = vars(args)['include']
    run_sync(**{"content_ids": ids, "include": include})
