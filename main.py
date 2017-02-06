import argparse
import asyncio
import json
import locale
import logging
import threading
import time
import urllib.parse
import urllib.request
import websockets

from argparse import RawTextHelpFormatter

def get_public_crest_data(type, id, href):
	api_versions = {
		"solarsystems": "System-v1",
		"regions": "Region-v1",
		"constellations": "Constellation-v1",
		"inventory/types": "ItemType-v3"
	}

	if href:
		request = urllib.request.Request(id)
	else:
		request = urllib.request.Request("https://crest-tq.eveonline.com/{0}/{1}/".format(type, id))

	request.add_header("Accept", "application/vnd.ccp.eve.{0}+json;charset=utf-8".format(api_versions[type]))
	request.add_header("Content-Type", "application/json")
	request.add_header("User-Agent", "zKill-WS Slack/1.1")

	endresult = urllib.request.urlopen(request)
	binstr = endresult.read()
	jsonstr = binstr.decode('ascii')
	return json.loads(jsonstr)

def send_slack(data):
	# Damage taken information.
	taken = {
		"title": "Attackers",
		"value": "{0} {1} ({2} Damage)".format(
			data['count'],
			"pilots" if data['count'] > 1 else "pilot",
			locale.format('%d', data['victim']['damageTaken'], grouping=True),
		),
		"short": True,
	}

	# Damage dealt information.
	if "id" in data['dealer']['character']:
		dealt = {
			"title": "Most Damage",
			"value": "<https://zkillboard.com/character/{0}|{1}> ({2} Damage)".format(
				data['dealer']['character']['id'],
				data['dealer']['character']['name'],
				locale.format('%d', data['dealer']['damageDone'], grouping=True)
			),
			"short": True,
		}
	else:
		dealt = {
			"title": "Most Damage",
			"value": "{0} ({1} Damage)".format(
				data['dealer']['character']['name'],
				locale.format('%d', data['dealer']['damageDone'], grouping=True)
			),
			"short": True,
		}

	# Ship type information.
	ship = {
		"title": 'Ship',
		"value": data['victim']['shipType']['name'],
		"short": True,
	}

	# Value information.
	value = {
		"title": 'Value',
		"value": locale.format("%.2f", data['zkb']['totalValue'], grouping=True) + " ISK",
		"short": True,
	}

	# Location information.
	loc_val = ""
	loc_val += "<https://zkillboard.com/system/{sid}|{sname}>"
	loc_val += " ({sec:.1f})"
	loc_val += " < "
	loc_val += "{cname}"
	loc_val += " < "
	loc_val += "<https://zkillboard.com/region/{rid}|{rname}>"

	location = {
		"title": 'Location',
		"value": loc_val.format(
			sid = data['system']['id'],
			sname = data['system']['name'],
			sec = data['system']['securityStatus'],

			cname = data['constellation']['name'],

			rid = data['region']['id'],
			rname = data['region']['name']
		),
		"short": False,
	}

	# Prep our color.
	color = "good"
	if data['victim'][entity_type] != None and data['victim'][entity_type]['id'] == entity_id:
		color = "danger"

	# Set up containers needed by slack.
	post = {
		"color": color,
		"fallback": data['victim']['character']['name'] + " was killed by " + data['killer']['character']['name'] + " (" + data['kill']['killTime'] + ")",
		"fields": [ship, value, taken, dealt, location],
		"thumb_url": "https://imageserver.eveonline.com/Render/" + str(data['victim']['shipType']['id']) + "_64.png",
		"title": data['victim']['character']['name'] + " was killed by " + data['killer']['character']['name'] + " (" + data['kill']['killTime'] + ")",
		"title_link": "https://zkillboard.com/kill/" + str(data['kill_id']) + "/",
	}

	# Add this kill to our attachments.
	attachments = [post]

	try:
		# Set up our data.
		payload = json.dumps({"attachments": attachments})
		send = urllib.parse.urlencode({"payload": payload})
		bin_data = send.encode('ascii')

		# Extra output for logging assistance.
		logging.info("Sending kill to slack: " + payload)

		# Set up our request.
		request = urllib.request.Request(webhook_url)
		request.add_header("User-Agent", "zKill-WS Slack/1.1")

		# Send the info, or ignor it, depending on dry run.
		if not dry_run:
			endresult = urllib.request.urlopen(request, bin_data)
			logging.info("Kill sent.")
			return endresult.read()
		else:
			logging.info("Kill ignored due to dry run.")
			return ""
	except urllib.request.HTTPError as e:
		logging.error("HTTPError in processing record: " + str(e.reason))
		logging.error(e.fp.read())
		logging.error(e.hdrs)
	except KeyError as e:
		logging.error("KeyError in processing record: " + str(e))
	except NameError as e:
		logging.error("NameError in processing record: " + str(e))
	except Exception:
		logging.error("Generic Exception in processing record: " + str(sys.exc_info()[0]) + " (" + str(sys.exc_info()[1]) + ")")

def process_kill(kill, zkb):
	# Kill ID.
	kill_id = kill['killID']

	# Location information.
	system = get_public_crest_data("solarsystems", kill['solarSystem']['id'], False)
	constellation = get_public_crest_data("constellations", system['constellation']['id'], False)
	region = get_public_crest_data("regions", constellation['region']['href'], True)

	# Victim information.
	victim = kill['victim']
	if victim['character'] == None or victim['character']['id'] == 0:
		victim['character'] = {'name': victim['shipType']['name']}

	# Functions for identifying people.
	def isNPC(char):
		if char['character'] == None or char['character']['id'] == 0:
			return True
		return False

	# Attacker information.
	killer = {}
	dealer = {'character': None, 'damageDone': 0}
	count = 0
	for attacker in kill['attackers']:
		# Increase our attacker count.
		count += 1

		# Check for final blow.
		if attacker['finalBlow'] == True:
			killer = attacker

		# Check for highest damage.
		if attacker['damageDone'] > dealer['damageDone']:
			if isNPC(attacker) and not isNPC(dealer):
				dealer = dealer
			else:
				dealer = attacker
		else:
			if isNPC(dealer) and not isNPC(attacker):
				dealer = attacker

	# Update some information if needed.
	if isNPC(killer):
		killer['character'] = {
			"id": 0,
			"name": killer['shipType']['name'],
		}

	if isNPC(dealer):
		dealer['character'] = {
			"id": 0,
			"name": dealer['shipType']['name'],
		}

	# Send the data along to be prepped and processed for slack.
	send_slack({
		"constellation": constellation,
		"count": count,
		"dealer": dealer,
		"kill": kill,
		"kill_id": kill_id,
		"killer": killer,
		"region": region,
		"system": system,
		"victim": victim,
		"zkb": zkb,
	})

def on_message(message, args):
	try:
		# Parse the JSON.
		kill = json.loads(message)

		# Does this killmail involve the entity?
		relevant = False

		if args.all:
			relevant = True

		for attacker in kill['killmail']['attackers']:
			if attacker[entity_type] != None and attacker[entity_type]['id'] == entity_id:
				# Entity is among the attackers.
				relevant = True

		if kill['killmail']['victim'][entity_type] != None and kill['killmail']['victim'][entity_type]['id'] == entity_id:
			# Entity is the victim.
			relevant = True

		# If entity is involved, process the kill.
		if relevant:
			logging.info("Kill Processing")
			process_kill(kill['killmail'], kill['zkb'])
		else:
			logging.info("Kill Ignored")
		return None
	except Exception as e:
		logging.error(str(e))
		logging.error(message)
		logging.info("Shutting down...")

class Pinger(object):
	def __init__(self):
		self.isRunning = True
		logging.debug("Pinger Initialized.")
	def run(self, websocket):
		while self.isRunning:
			logging.debug("Pinging for keepalive: " + str(self.isRunning) + ".")
			websocket.ping()
			time.sleep(10)

if __name__ == "__main__":
	# Set locale.
	try:
		locale.setlocale(locale.LC_ALL, "en_US.utf8")
	except:
		locale.setlocale(locale.LC_ALL, "english")

	# Defining globals so we have them available throughout.
	global dry_run
	global entity_id
	global entity_type
	global webhook_url

	# Set some defaults.
	entity_id = 0
	entity_type = "alliance"
	webhook_url = ""

	# Set up all our argument bullshit.
	parser = argparse.ArgumentParser(
		add_help = False,
		description = "Daemon used to process EVE: Online kills from the pizza zKillboard websocket relay and post them to slack. (https://github.com/xxpizzaxx/zkb-ws-relay)",
		formatter_class = RawTextHelpFormatter,
	)

	parser.add_argument(
		"-h", "--help",
		action = "help",
		help = "\nShow this help message.\n\n",
	)

	parser.add_argument(
		"-a", "--all",
		action = "store_true",
		default = False,
		dest = "all",
		help = "\nFlag to tell the daemon to post all kills, ignoring the '-c' and '-e' flags.\n\n",
	)

	parser.add_argument(
		"-c", "--corporation",
		action = "store_true",
		default = False,
		dest = "corp",
		help = "\nFlag to tell the daemon that the given ID is for a corporation rather than an alliance.\n\n",
	)

	parser.add_argument(
		"-d", "--dry_run",
		action = "store_true",
		default = False,
		dest = "dry",
		help = "\nFlag to tell the daemon to simply parse and log kills, but not post them to slack. Good for debugging.\n\n",
	)

	parser.add_argument(
		"-e", "--entity_id",
		action = "store",
		dest = "eid",
		help = "\nID of the group to search for the kills of. By default, this should be an Alliance ID. If the '-c' flag is supplied, this will assume a Corporation ID.\n\n",
		required = True,
	)

	parser.add_argument(
		"-f", "--log_file",
		action = "store",
		default = None,
		dest = "logf",
		help = "\nThe file to write to for all logging.\n\n",
	)

	parser.add_argument(
		"-l", "--log_level",
		action = "store",
		choices = ["INFO", "DEBUG", "WARNING", "ERROR", "CRITICAL"],
		default = "INFO",
		dest = "logl",
		help = "\nThe level of logging to print.\n\n",
	)

	parser.add_argument(
		"-w", "--webhook_url",
		action = "store",
		dest = "url",
		help = "\nWebhook URL from slack that the daemon will post to.\n\n",
		required = True,
	)

	args = parser.parse_args()

	# Change anything from defaults to whatever was supplied.
	entity_id = args.eid
	if args.corp:
		entity_type = "corporation"
	webhook_url = args.url
	dry_run = args.dry

	# Set up our logging.
	if args.logl == "INFO":
		logging.basicConfig(
			filename = args.logf,
			format = "[%(asctime)s] [%(levelname)8s] (LN %(lineno)s): %(message)s",
			level = logging.INFO,
		)
	elif args.logl == "DEBUG":
		logging.basicConfig(
			filename = args.logf,
			format = "[%(asctime)s] [%(levelname)8s] (LN %(lineno)s): %(message)s",
			level = logging.INFO,
		)
	elif args.logl == "WARNING":
		logging.basicConfig(
			filename = args.logf,
			format = "[%(asctime)s] [%(levelname)8s] (LN %(lineno)s): %(message)s",
			level = logging.INFO,
		)
	elif args.logl == "ERROR":
		logging.basicConfig(
			filename = args.logf,
			format = "[%(asctime)s] [%(levelname)8s] (LN %(lineno)s): %(message)s",
			level = logging.INFO,
		)
	elif args.logl == "CRITICAL":
		logging.basicConfig(
			filename = args.logf,
			format = "[%(asctime)s] [%(levelname)8s] (LN %(lineno)s): %(message)s",
			level = logging.INFO,
		)

	# Set up our websocket crap.
	pinger = Pinger()
	async def receive(pinger):
		async with websockets.connect("wss://api.pizza.moe/stream/killmails/") as websocket:
			ping_thread = threading.Thread(target = pinger.run, args = (websocket,))
			ping_thread.start()
			while True:
				message = await websocket.recv()
				logging.info("Message Received: " + message)
				thread = threading.Thread(target = on_message, args = (message,args))
				thread.start()

	try:
		asyncio.get_event_loop().run_until_complete(receive(pinger))
	except (KeyboardInterrupt, Exception) as e:
		if not isinstance(e, KeyboardInterrupt):
			logging.error(str(e))
		logging.info("Shutting down...")
		pinger.isRunning = False

