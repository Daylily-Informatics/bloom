from bloom_lims.bdb import BLOOMdb3
from bloom_lims.bdb import BloomWorkflow, BloomWorkflowStep, BloomObj
import sys
import os
 
from graphviz import Digraph
from sqlalchemy import MetaData

# Your existing ORM definitions go here
# ...

# Initialize Graphviz Digraph for schema visualization
dot = Digraph(comment='Database Schema')

# Function to create label for tables (nodes)
def create_label(class_name, columns, base_class_name=None):
    label = f"{class_name}"
    if base_class_name:
        label += f" (inherits {base_class_name})"
    label += "|"
    label += "|".join(f"<{col.name}> {col.name}" for col in columns)
    return label

# Function to add foreign key and inheritance relations (edges)
def add_edges(dot, class_name, columns, base_class_name=None):
    if base_class_name:
        dot.edge(base_class_name, class_name, label="inherits")
    for col in columns:
        if hasattr(col, 'foreign_keys') and col.foreign_keys:
            for fk in col.foreign_keys:
                ref_table = fk.column.table.name
                dot.edge(f"{class_name}:{col.name}", f"{ref_table}:{fk.column.name}")

bob_wf = BloomWorkflow(BLOOMdb3())

# Use the MetaData instance to reflect the database tables
metadata = MetaData()
metadata.reflect(bind=BLOOMdb3().engine)

# Add tables (nodes) and relationships (edges) to the graph
for class_name, cls in bob_wf.Base._decl_class_registry.items():
    if hasattr(cls, '__table__'):
        base_class_name = cls.__base__.__name__ if hasattr(cls, '__base__') else None
        dot.node(class_name, create_label(class_name, cls.__table__.columns, base_class_name), shape='record')
        add_edges(dot, class_name, cls.__table__.columns, base_class_name)

# Save or render the diagram
dot.render('database_schema', view=True)
