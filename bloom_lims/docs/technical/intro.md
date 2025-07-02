# Problem Statement
* In my experience, laboratory information systems (LIS or LIMS) do not satisfactorily meet the needs of most of the end users ( lab staff, operations, informatics ), are expensive and time consuming to build/maintain/extend, and often are built to a narrow scope when these systems usually need to be broad in scope. This has been the case for so long that these are the expected characteristics of LIS. Current LIS, as irritating as they are, do offer sigificant value and modern labs simply can not operate w/out one. In my experience, these sytems invariably also end up at best a moderate inconvenience to work with/around, or are actually business killing. Why?

# Why?
## preamble
I've worked with LIS, both building from first principles and working with commercial solutions for almost 30 years. And, all of the experiences suffered, to one degree or another, the stereotypical LIMS negatives. This situation has increasingly puzzled me. I was failing to get my thoughts on paper, and wondered if writing code might help... also I was looking for a substantial project to collaborate with chatGPT4 on. The experiment was a success in helping clarify my thoughts & to my great suprise, resulted in a viable LIMS, _Bloom_.

## What Is Up With Unsatisfactory LIMS Being The Norm?
The following are observations and hypotheses as to what drives this 'LIMS situation' drawn from my involvement with all of these patterns and antipatterns at one time or another.  _Bloom_ will test some hypotheses & if successful improve the state of the art. 
 

### Inadequate Requirements && Design Principles Mismatch The Problem Domain
LIMS stakeholders do not include all stakeholders & those included typically come to the table with design principles rooted in manual processes engineering. Folks implementing LIMS often come to the table w/formal software engineering design principles, and no experience building systems like these. When the LIMS implementation folks have had experience building systemns like these, they often engage not as partners but short order cooks doing what they are told (I am being parabolic). 




## Patterns
### Identifiers 
* Identifiers should uniquely identify one thing, and one thing only. If any object is transformed, the transofrmed thing should have a new identifier.
* Identifiers should not encode any metadata about the thing they identify. (this can not be stressed enough, and there is a small exception)
* UUIDs are fine for s/w systems, but are not suitable for human use. Particularly when these identifiers must be printed on labels applied to various sized labware.
* Enterprise UIDs are a good choice for human use, and more suitable for fitting on labels. An euid prefix can encode the class of the thing it identifies... this can be useful shorthand in operational settings when talking about 'things'.

### Optimize for robustness of data, not human convenience
* A LIMS will often require processes which are not convenient for humans to execute, especially when compared to manual processes, where shortcuts seem effortless b/c no external system needs to understand these shortcuts. These inconveinient or more time consuming processes are good candidates for automation.

### Understand the process, then adjust it to best work with a LIMS
* Moving a manual process, or any non-LIMSified process, wholesale into a LIMS will result in failing to leverage many advantages a LIMS offers and can yield a solution which amplifies the weaknesses of both the process and the LIMS.

### Object Relationships
* Given any identifier, a LIMS should be able to repory the complete history of that thing, including all transformations, and all relationships to other things. 

### Audit Trails
* All changes to object properties, relationsships, and even creation and deletion operations should be recorded and accessible.
 
### All LIMS Stakehoders Should Contribute To Requirements
* This includes: lab staff, operations, informatics, requlatory & compliance, and any other stakeholder who will interact with the LIMS.
### Failure of Imagination

### Cultural Stance On Errors
* LIMS will expose many places in a process where errors are happening, and are now visible. This should be anticipated, and approached as a success for the LIMS in identifying a place for improvement.  This is a cultural stance. An environment where errors are feared, or believed not to happen, will result in people working around the LIMS.


### The Pursuit of Perfection Is Pathological
* Intertangled with the cultural stance on errors.  Perfection is, arguably, not an aceivable state, and can lead to a false sense of security.
 
### Regulatory and Compliance Requirements Are A Great Starting Point
* Meeting req & compli requirements is a must. How these are met should be for the implementation crew to offer solutions on.

## Anti-Patterns
### Identifiers 
* Including metadata in identifiers.
* Adding leading zeros to identifiers, even if following an euid prefix.
* Reusing idetifiers for child objects. 

### Requirements Gathering

#### Preemptive Optimization / Filtering
* If stakeholders decide some feature is too hard to create, and never ask for it, it will never be created. This pattern is very common.

#### Dismissing Complexity
* ... see concept shortcuts

#### Excluding Edge Cases // Failing To Push On Stakeholder Requirements
Preemptive optimization is a special case of this one. The situation usually is a variation of:
* Stakeholder: "We need to be able to move a sample from one tube to a second tube."
* Implementer: "Ok, and that is all you need to do? "
* Stakeholder: "Yes, that is all we need to do."

However, if the Implementer asks a slightly different question instead:
* Implementer: "Are there any other operations you need to execute on the sample? Any edge cases? Ever?"

The answer will very nearly always be some version of:
* Stakeholder: "Well, occasionally, we need to store the empty tube and fill it with buffer to run another assay... but that is rare. The LIMS does not need to track this. And when we dispose of the original tube, we record that, but there is a paper log for that. etc, etc."

Failing to probe, or not realzing the need to probe, will result in a LIMS built to such an oversimplified spec it will fail to be useful out of the gate, and often these additional 'rare' requirements are not challenging to add and provide significant user value.

##### ^^^ And here we have one of the most common sources of LIMS crappiness.

### Regulatory and Compliance Requirements As The Target
* Inadequate & by definition, years out of date.  These are a great starting point, but should not be the target. 

### Implementation
#### Conceptual Shortcuts
This is one of the most significant drivers in fragile/inadquate LIMS. Conceptual shortcuts offer quicker implementation at the expense of longer term flexibility, and these shortcuts will frequently be advocated for by both stakeholders and implementers.
ie:
* Not modeling wells in a plate, b/c they are always copied exactly from a parent plate.
* Conflating the container and the contents of a container. (the blood in a tube should have a unique ID from the tube)
* Reuising identifiers for child objects. (you now have comprimized the ability to track the history of this object and its children sharing this id)



# Bloom Design Principles
The above is not a comprehensive set of considerations, but a good start.  [These considerations coalesced into the following design principles I went to great lengths to adhere to while building Bloom](./design_principles.md).



