import easy_biologic as ebl
import easy_biologic.base_programs as blp

# create device
bl = ebl.BiologicDevice('192.168.0.10')

# create mpp program
params = {
	'run_time': 10		
}

mpp = blp.MPP(
    bl,
    params, 	
    channels = [ 0, 1, 2, 3, 4, 5, 6 ]        
)

# run program
mpp.run('data')