#!/usr/bin/env python3

import area_server
import occasional

import dill
dill.settings['recurse'] = True


def f():
    h = area_server.start()

    s1 = ("rectangle", 3,4)
    area1 = area_server.area(h,s1)
    assert(area1 == 12)
    print(f"{s1}: {area1}")


    s2 = ("circle", 5)
    area2 = area_server.area(h,s2)
    assert(abs(78.53975 - area2) < 0.001)
    print(f"{s2}: {area2}")

    s3 = "rhombicosidodecahedron"
    area3 = area_server.area(h,s3)
    assert(area3 == ("error", "rhombicosidodecahedron"))
    print(f"{s3}: {area3}")

    area_server.stop(h)

if __name__ == "__main__":
    occasional.run(f)
