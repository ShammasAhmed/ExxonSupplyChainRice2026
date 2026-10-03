import numpy as np
import pandas as pd
import networkx as nx
import gurobipy as gp
from gurobipy import GRB

## Extracting data from the excel file

network = pd.read_excel("network.xlsx", sheet_name=None)

sources = network['Sources']
sinks = network['Sinks']
# edges = network['Edges']

sources = sources.set_index("Name")
source_names = sources.index.tolist()

sinks = sinks.set_index("Facility Name")
sink_names = sinks.index.tolist()

# Manually create edges between any two source-sink nodes
edges = []
for source in source_names:
    for sink in sink_names:
        edges.append((source, sink))


## Creating the Gurobi model
model = gp.Model("ExxonNASupplyChain")
model.addVars(edges, name="x", vtype=GRB.CONTINUOUS, lb=0)
