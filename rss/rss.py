import json
import pika
import time
import logging
import argparse
import datetime
import utilities
import pattern.web
from multiprocessing import Pool


def get_rss(address, website):
    """
    Function to parse an RSS feed and extract the relevant links.

    Parameters
    ----------

    address: String.
                Address for the RSS feed to scrape.

    website: String.
                Nickname for the RSS feed being scraped.

    Returns
    -------

    results : pattern.web.Results.
                Object containing data on the parsed RSS feed. Each item
                represents a unique entry in the RSS feed and contains relevant
                information such as the URL and title of the story.

    """
    try:
        results = pattern.web.Newsfeed().search(address, count=100,
                                                cached=False, timeout=30)
        logging.debug('There are {} results from {}'.format(len(results),
                                                            website))
    except Exception, e:
        print 'There was an error. Check the log file for more information.'
        logging.warning('Problem fetching RSS feed for {}. {}'.format(address,
                                                                      e))
        results = None

    return results


def process_rss(rss_result, message_body, redis_conn, message_queue):
    for result in rss_result:
        page_url = _convert_url(result.url, message_body['website'])

        in_database = _check_redis(page_url, redis_conn)

        message_body['title'] = result.title
        message_body['date'] = result.date
        message_body['url'] = page_url

        to_send = json.dumps(message_body)

        if not in_database:
            message_queue.basic_publish(exchange='',
                                        routing_key='scraper_queue',
                                        body=to_send,
                                        properties=pika.BasicProperties(
                                            delivery_mode=2,))
            #Set the value within redis to expire in 3 days
            redis_conn.setex(page_url, 259200, 1)
        else:
            pass


def _convert_url(url, website):
    """
    Private function to clean a given page URL.

    Parameters
    ----------

    url: String.
            URL for the news stories to be scraped.

    website: String.
                Nickname for the RSS feed being scraped.

    Returns
    -------

    page_url: String.
                Cleaned and unicode converted page URL.
    """

    if website == 'xinhua':
        page_url = url.replace('"', '')
        page_url = page_url.encode('ascii')
    elif website == 'upi':
        page_url = url.encode('ascii')
    elif website == 'zaman':
        #Find the weird thing. They tend to be ap or reuters, but generalized
        #just in case
        com = url.find('.com')
        slash = url[com + 4:].find('/')
        replaced_url = url.replace(url[com + 4:com + slash + 4], '')
        split = replaced_url.split('/')
        #This is nasty and hackish but it gets the jobs done.
        page_url = '/'.join(['/'.join(split[0:3]), 'world_' + split[-1]])
    else:
        page_url = url.encode('utf-8')

    return page_url


def _check_redis(url, db_collection):
    """
    Private function to check if a URL appears in the database.

    Parameters
    ----------

    url: String.
            URL for the news stories to be scraped.

    db_collection: pymongo Collection.
                        Collection within MongoDB that in which results are
                        stored.

    Returns
    -------

    found: Boolean.
            Indicates whether or not a URL was found in the database.
    """

    found = False
    if db_collection.get(url):
        found = True

    return found


def process_whitelist(filepath):
    to_scrape = dict()
    if filepath:
        url_whitelist = open(filepath, 'r').readlines()
        url_whitelist = [line.replace('\n', '').split(',') for line in
                         url_whitelist if line]
        to_scrape = {listing[0]: [listing[1], listing[3]] for listing in
                     url_whitelist}

    return to_scrape


def scrape_func(website, address, lang, args):
    logging.info('Processing {}. {}'.format(website, datetime.datetime.now()))

    redis_conn = utilities.make_redis(args.redis_conn)
    channel = utilities.make_queue(args.rabbit_conn)

    body = {'address': address, 'website': website, 'lang': lang}
    results = get_rss(address, website)

    if results:
        process_rss(results, body, redis_conn, channel)
    else:
        logging.warning('No results for {}.'.format(website))
        pass


def main(scrape_dict, args):

    pool = Pool(30)

    while True:
        logging.info('Starting a new scrape. {}'.format(datetime.datetime.now()))
        results = [pool.apply_async(scrape_func,
                                    (website, address, lang, args)) for
                   website, (address, lang) in scrape_dict.iteritems()]
        timeout = [res.get(9999999) for res in results]
        logging.info('Finished a scrape. {}'.format(datetime.datetime.now()))
        time.sleep(1800)


if __name__ == '__main__':
    #Get the info from the config
    time.sleep(60)
    config_dict = utilities.parse_config()

    aparse = argparse.ArgumentParser(prog='rss')
    aparse.add_argument('-rb', '--rabbit_conn', default='localhost')
    aparse.add_argument('-rd', '--redis_conn', default='localhost')
    args = aparse.parse_args()

    logging.basicConfig(format='%(levelname)s %(asctime)s: %(message)s',
                        level=logging.INFO)

    logging.info('Running. Processing in 45 min intervals.')

    print('Running. See log file for further information.')

    #Convert from CSV of URLs to a dictionary
    try:
        to_scrape = process_whitelist('/src/whitelist_urls.csv')
    except IOError:
        print 'There was an error. Check the log file for more information.'
        logging.warning('Could not open URL whitelist file.')

    main(to_scrape, args)
