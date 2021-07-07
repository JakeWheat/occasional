
.PHONY : dynamic_test
dynamic_test :
	PYTHONPATH=.:test_framework:tests:examples test_framework/test_framework.py -j1 -g tests/*.py

all_tests.py : tests/*.py
	PYTHONPATH=.:test_framework:tests:examples test_framework/test_framework.py -g tests/*.py --generate-source > all_tests.py


.PHONY : test
test : all_tests.py
	PYTHONPATH=.:test_framework:tests:examples python3 all_tests.py -j1

.PHONY : area_server_example
area_server_example :
	PYTHONPATH=. examples/area_server_client.py
