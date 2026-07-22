%% *Matlab Live Tutorial*
% Below, you will find a quick tutorial to view the electrophysiology and behavioral 
% data which relates to:
%% 
% * Paper: <https://doi.org/10.1016/j.celrep.2025.115768 https://doi.org/10.1016/j.celrep.2025.115768>
% * Dataset: <https://doi.org/10.63884/ndic.2025.jyxfer8m https://doi.org/10.63884/ndic.2025.jyxfer8m>
%% Download NDI
% In order to view the dataset, you will need access to the NDI platform. Follow 
% the instructions found at <https://vh-lab.github.io/NDI-matlab/NDI-matlab/installation/ 
% https://vh-lab.github.io/NDI-matlab/NDI-matlab/installation/> to download NDI 
% and gain access to the suite of tools we have created!
%% Import the NDI dataset
% Define the dataset path and id.

% Choose the folder where the dataset is (or will be) stored
dataPath = [userpath filesep 'Datasets']; % (e.g. /Users/myusername/Documents/MATLAB/Datasets)
cloudDatasetId = '67f723d574f5f79c6062389d';
datasetPath = fullfile(dataPath,cloudDatasetId);
% Download or load the NDI dataset 
% The first time you try to access the data, it needs to be downloaded from 
% NDI-cloud. This may take a few minutes. Once you have the dataset downloaded, 
% every other time you examine the data you can just load it.

if isfolder(datasetPath)
    % Load if already downloaded
    dataset = ndi.dataset.dir(datasetPath);
else
    % Download
    if ~isfolder(dataPath), mkdir(dataPath); end
    dataset = ndi.cloud.downloadDataset(cloudDatasetId,dataPath);
end
% Retrieve the NDI session
% A dataset can have multiple sessions, but this dataset has only one. We must 
% retrieve it in order to access the accompanying experimental *probes* (i.e. 
% a virtual or physical instrument that makes a measurement of or produces a stimulus 
% for a *subject*).

% Retrieve the session from this dataset
[session_ref_list,session_list] = dataset.session_list();
session = dataset.open_session(session_list{1});
%% View subjects, probes and epochs
% View subject summary table
% Each individual animal is referred to as a *subject* and has a unique alphanumeric 
% |subject_id| along with a |subject_name| which contains references to the animal's 
% strain, species, genotype, experiment date, and cell type. Our database contains 
% documents which store metadata about each *subject* including their species, 
% strain, genetic strain type, and biological sex which are linked to well-defined 
% ontologies such as <https://www.ncbi.nlm.nih.gov/Taxonomy/Browser/wwwtax.cgi?mode=Info&id=10116&lvl=3&lin=f&keep=1&srchmode=1&unlock 
% NCBI>, <https://rgd.mcw.edu/rgdweb/report/strain/main.html?id=13508588 RRID>, 
% and <https://www.ebi.ac.uk/ols4/ontologies/pato/classes/http%253A%252F%252Fpurl.obolibrary.org%252Fobo%252FPATO_0000384 
% PATO>. Additionally, metadata about any *treatments* that a *subject* received 
% such as the location of optogenetic stimulation are stored. A summary table 
% showing the metadata for each *subject* can be viewed below.

% View summary table of all subject metadata
subjectSummary = ndi.fun.docTable.subject(dataset)
% Filter subjects
% We have created tools to filter a table by its values. Try finding *subjects* 
% matching a given criterion.
% 
% Examples:
%% 
% # |columnName = StrainName          dataValue = AVP-Cre|
% # |columnName = StrainName          dataValue = SD|

% Search for subjects
columnNamesSubject = subjectSummary.Properties.VariableNames;
columnName = columnNamesSubject(4);
dataValue = "AVP-Cre";
rowInd = ndi.fun.table.identifyMatchingRows(subjectSummary,...
    columnName{1},dataValue,'stringMatch','contains');
filteredSubjects = subjectSummary(rowInd,:)
% View probe and epoch summary tables
% In the NDI framework, a *probe* is an instrument that makes a measurement 
% of or produces a stimulus for a *subject*. Probes are part of a broader class 
% of experiment items that we term *elements.* In these experiments, there are 
% 3 probe types:
%% 
% # |stimulator|
% # |patch-Vm|
% # |patch-I|
%% 
% Each subject is linked to a unique set of probes. The *stimulator* probe is 
% connected to any information about stimuli that the subject received such as 
% electrophysiological bath conditions or experimental approaches (e.g. optogenetic 
% tetanus). The *patch-Vm* and *patch-I* are probes of type *mfdaq* (multifunction 
% data acquisition system) which means that they contain data linked to an acquisition 
% system that stored measurements (i.e. voltage and current) for a set of experimental 
% *epochs*. Each *epoch* corresponds to one of the original |.mat| files.

% View summary table of all probe metadata
probeSummary = ndi.fun.docTable.probe(dataset)
% View summary table of all epoch metadata for each probe
epochSummary = ndi.fun.docTable.epoch(session) % this may take a few minutes
% Combine metadata tables
% Let's combine all metadata so that there is one row per *epoch*.

% Combine all metadata into one table
combinedSummary = ndi.fun.table.join({subjectSummary,probeSummary,epochSummary},...
    'uniqueVariables','EpochDocumentIdentifier');
combinedSummary = ndi.fun.table.moveColumnsLeft(combinedSummary,...
    {'SubjectLocalIdentifier','EpochNumber'})
% Filter epochs
% Try finding *epochs* matching a given criterion.
% 
% Examples:
%% 
% # |columnName = ApproachName     dataValue = optogenetic           stringMatch 
% = contains|
% # |columnName = MixtureName      dataValue = FE201874              stringMatch 
% = contains|
% # |columnName = CellTypeName     dataValue = Type I BNST neuron    stringMatch 
% = identical|
% # |columnName = global_t0        dataValue = Jun-2023              stringMatch 
% = contains|

% Search for epochs
columnNamesCombined = combinedSummary.Properties.VariableNames;
columnName = columnNamesCombined(27);
dataValue = "Jun-2023";
stringMatch = "contains";
rowInd = ndi.fun.table.identifyMatchingRows(combinedSummary,...
    columnName{1},dataValue,'stringMatch',stringMatch{1});
filteredEpochs = combinedSummary(rowInd,:)
%% Plot electrophysiology data
% Each *subject* is associated with a set of experimental *epochs.* One *epoch* 
% corresponds to one of the original |.mat| files. Select a *subject* from the 
% dropdown control below to view that subject's *epochs* and the associated stimulus 
% conditions for each epoch. This may take a minute to load.

% Select a subject
subjectID = subjectSummary.SubjectDocumentIdentifier;
subjectNames = subjectSummary.SubjectLocalIdentifier;
subjectName = subjectNames(74);
subjectIndex = strcmpi(subjectNames,subjectName);
epochIndex = ndi.fun.table.identifyMatchingRows(combinedSummary,...
    'SubjectDocumentIdentifier',subjectID{subjectIndex});

% Check that the subject has epochs
if ~any(epochIndex)
    error(['This subject is part of the behavioral dataset. ' ...
        'Please select a subject in the electrophysiology dataset.'])
end

% View summary table of epochs for this subject
epochConditions = combinedSummary(epochIndex,:)
% Get the patch-Vm probe
patchVm = session.getprobes('subject_id',subjectID{subjectIndex},...
    'type','patch-Vm');
patchVm = patchVm{1};

% Get the patch-I probe
patchI = session.getprobes('subject_id',subjectID{subjectIndex},...
    'type','patch-I');
patchI = patchI{1};
%% 
% Select an *epoch* to view the associated electrophysiology traces. This may 
% take a minute to load.

% Select an epoch
epochNums = epochConditions.EpochNumber;
epochNum = epochNums(4);

% Read the patch-Vm timeseries
[dataVm,time] = patchVm.readtimeseries(epochNum,-inf,inf);

% Read the patch-I timeseries
[dataI,~] = patchI.readtimeseries(epochNum,-inf,inf);

% Find indices where traces start and end
traceStarts = find(diff([1;isnan(dataI)]) == -1);
traceEnds = find(diff([isnan(dataI);0]) == 1);

% Get number of current steps and number of timepoints per step
numSteps = numel(traceStarts);
numTimepoints = max(traceEnds - traceStarts) + 1;

% Reformat data into a matrix (time x steps)
timeMatrix = time(1:numTimepoints);
dataVmMatrix = nan(numTimepoints,numSteps);
dataIMatrix = nan(numTimepoints,numSteps);
for i = 1:numSteps
    dataVmMatrix(:,i) = dataVm(traceStarts(i):traceEnds(i));
    dataIMatrix(:,i) = dataI(traceStarts(i):traceEnds(i));
end

% Get current step values
[~,rowInd] = max(abs(dataIMatrix));
colInd = 1:size(dataIMatrix,2);
ind = sub2ind(size(dataIMatrix),rowInd,colInd);
currentSteps = dataIMatrix(ind);

% Plot reformatted traces
figure; hold on; ax = gca;
colormap(ax, turbo); clim(ax, [min(currentSteps) max(currentSteps)]);
colors = turbo(max(currentSteps) - min(currentSteps) + 1);
for i = 1:size(dataVmMatrix, 2) % Iterate through each column of dataVmMatrix
    colorInd = currentSteps(i) - min(currentSteps) + 1;
    plot(ax,timeMatrix, dataVmMatrix(:, i), 'Color', colors(colorInd, :));
end
xlabel('Time (s)'); ylabel('Voltage (mV)')
cb = colorbar(ax); cb.Label.String = 'Current (pA)';
%% Plot Elevated Plus Maze data

% Get Elevated Plus Maze documents/table
query = ndi.query('ontologyTableRow.names','contains_string','Elevated Plus Maze');
docsEPM = session.database_search(query);
tableEPM = ndi.fun.doc.ontologyTableRowDoc2Table(docsEPM); tableEPM = tableEPM{1};
varEPM = tableEPM.Properties.VariableNames;

% Get list of all variables
[fullNames,shortNames,ontologyNodes] = ...
    ndi.fun.doc.ontologyTableRowVars(session);

% Reorganize table variables
tableEPM = ndi.fun.table.moveColumnsLeft(tableEPM,{'SubjectLocalIdentifier',...
    'Treatment_CNOOrSalineAdministration','ExperimentalGroupCode',...
    'ElevatedPlusMaze_TestIdentifier','DataExclusionFlag'})
%% 
% Select a variable to view it's definition and plot the data.

% Define grouping and plotting variables
groupingVariable = 'Treatment_CNOOrSalineAdministration';
plottingVariable = varEPM(3);
plottingVariable = plottingVariable{1};

% Look up the variable in the ontology
termIndex = strcmpi(shortNames,plottingVariable);
termID = ontologyNodes{termIndex};
[id,name,prefix,definition,synonyms,shortName] = ...
    ndi.ontology.lookup(termID);

% Get valid row indices
validationFunc = @(x) isnumeric(x) && isscalar(x) && ~isnan(x);
validRows = ~tableEPM.DataExclusionFlag; % missing mCherry expression
if iscell(tableEPM.(plottingVariable)) % missing data points
    validRows = validRows & cellfun(validationFunc,tableEPM.(plottingVariable)); 
else
    validRows = validRows & arrayfun(validationFunc,tableEPM.(plottingVariable));
end

% Display the variable's id, name, definition, and short name
termInfo = cell2table({id,name,definition,shortName}',...
    'RowNames',{'id','name','definition','shortName'},...
    'VariableNames',{'value'})
% Plot data
x = categorical(tableEPM{validRows,groupingVariable});
y = tableEPM{validRows,plottingVariable}; if iscell(y), y = cell2mat(y); end
figure; violinplot(y,x,'GroupOrder',{'Saline','CNO'});
ylabel(fullNames{termIndex})
%% Plot Fear-Potentiated Startle data

% Get Fear-Potentiated documents/table
query = ndi.query('ontologyTableRow.names','contains_string','Fear-Potentiated Startle');
docsFPS = session.database_search(query);
tableFPS = ndi.fun.doc.ontologyTableRowDoc2Table(docsFPS); tableFPS = tableFPS{1};

% Reorganize table variables
tableFPS = ndi.fun.table.moveColumnsLeft(tableFPS,{'Fear_potentiatedStartle_ExperimentalPhaseOrTestName',...
    'SubjectLocalIdentifier'})
%% 
% We can reanalyze this data to get values such as the % of cued and non-cued 
% fear.

% Get list of all variables
[fullNames,shortNames,ontologyNodes] = ...
    ndi.fun.doc.ontologyTableRowVars(session);

% Get average startle amplitude for each context, subject, and trial
tableStartleAmplitude = groupsummary(tableFPS,...
    {'Fear_potentiatedStartle_ExperimentalPhaseOrTestName','SubjectLocalIdentifier',...
    'Fear_potentiatedStartle_TrialTypeIdentifier'},...
    'mean','AcousticStartleResponse_MaximumAmplitude');
experimentalPhases = unique(tableStartleAmplitude.Fear_potentiatedStartle_ExperimentalPhaseOrTestName);
experimentalPhases = experimentalPhases(contains(experimentalPhases,'Cue test'));

% Get row indices corresponding to each trial type
lightNoiseRows = strcmpi(tableStartleAmplitude.Fear_potentiatedStartle_TrialTypeIdentifier,'FPS (L+N) Testing Trial');
noiseOnlyRows = strcmpi(tableStartleAmplitude.Fear_potentiatedStartle_TrialTypeIdentifier,'FPS (N) Testing Trial');
startleRows = strcmpi(tableStartleAmplitude.Fear_potentiatedStartle_TrialTypeIdentifier,'Startle 95 dB Trial');

% Get tables of startle amplitude for each trial type
tableLightNoise = tableStartleAmplitude(lightNoiseRows,...
    {'Fear_potentiatedStartle_ExperimentalPhaseOrTestName','SubjectLocalIdentifier','mean_AcousticStartleResponse_MaximumAmplitude'});
tableNoiseOnly = tableStartleAmplitude(noiseOnlyRows,...
    {'Fear_potentiatedStartle_ExperimentalPhaseOrTestName','SubjectLocalIdentifier','mean_AcousticStartleResponse_MaximumAmplitude'});
tableStartle = tableStartleAmplitude(startleRows,...
    {'Fear_potentiatedStartle_ExperimentalPhaseOrTestName','SubjectLocalIdentifier','mean_AcousticStartleResponse_MaximumAmplitude'});

% Rename startle amplitude variable
tableLightNoise = renamevars(tableLightNoise,'mean_AcousticStartleResponse_MaximumAmplitude','startleAmplitudeLightNoise');
tableNoiseOnly = renamevars(tableNoiseOnly,'mean_AcousticStartleResponse_MaximumAmplitude','startleAmplitudeNoiseOnly');
tableStartle = renamevars(tableStartle,'mean_AcousticStartleResponse_MaximumAmplitude','startleAmplitudeStartle');

% Join trial type tables
tableCueTest = join(tableLightNoise,tableNoiseOnly,...
    'Keys',{'Fear_potentiatedStartle_ExperimentalPhaseOrTestName','SubjectLocalIdentifier'});
tableCueTest = join(tableCueTest,tableStartle,...
    'Keys',{'Fear_potentiatedStartle_ExperimentalPhaseOrTestName','SubjectLocalIdentifier'});

% Calculate cued fear %
tableCueTest.cuedFear = 100*(tableCueTest.startleAmplitudeLightNoise - ...
    tableCueTest.startleAmplitudeNoiseOnly)./...
    tableCueTest.startleAmplitudeNoiseOnly; % 100*(LN - N)/N

% Calculate non-cued fear %
tableCueTest.nonCuedFear = 100*(tableCueTest.startleAmplitudeNoiseOnly - ...
    tableCueTest.startleAmplitudeStartle)./...
    tableCueTest.startleAmplitudeStartle; % 100*(N - S)/S

varFPS = tableCueTest.Properties.VariableNames;

% Display table
tableCueTest
%% 
% Select an experimental phase and variable to plot the data.

% Choose an experimental phase
experimentalPhase = experimentalPhases(2);

% Define grouping and plotting variables
groupingVariable = 'Treatment_CNOOrSalineAdministration';
plottingVariable = varFPS(6);
plottingVariable = plottingVariable{1};

% Add grouping variable info from EPM table
tableCueTest = join(tableCueTest,tableEPM(:,{'SubjectLocalIdentifier',groupingVariable}));

% Get row indices corresponding to the experimental phase
phaseRows = strcmpi(tableCueTest.Fear_potentiatedStartle_ExperimentalPhaseOrTestName,experimentalPhase{1});

% Plot data
x = categorical(tableCueTest{phaseRows,groupingVariable});
y = tableCueTest{phaseRows,plottingVariable};
figure; violinplot(y,x,'GroupOrder',{'Saline','CNO'});
ylabel(plottingVariable)
