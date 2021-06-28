
from occasional import send, receive, slf
import occasional
import area_server

def test_area_server(trp):
    def f():
        ah = area_server.start()
        trp.assert_equal("rect area",
                         12, 
                         area_server.area(ah,("rectangle", 3,4)))
        trp.assert_true("circle area",
                        abs(78.53975 - area_server.area(ah,("circle", 5))) < 0.001)
        trp.assert_equal("rhombicosidodecahedron area",
                         area_server.area(ah,("rhombicosidodecahedron", 1)),
                         ("error", ("rhombicosidodecahedron", 1)))
        area_server.stop(ah)
    occasional.run(f)
