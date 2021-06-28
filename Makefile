
.PHONY : test
test :
	PYTHONPATH=.:test_framework:tests:examples test_framework/test_framework.py -j1 -g tests/*.py

.PHONY : area_server_example
area_server_example :
	PYTHONPATH=. examples/area_server_client.py
