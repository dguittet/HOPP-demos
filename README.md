# HOPP-demos

This repo contains scripts for running HOPP optimizations, the input files that define the technoeconomic parameters, the result files of the optimal designs, and Jupyter notebooks for analyzing the case studies.

### Installing HOPP-demos

1. Install the HOPP package from Source, following the Instructions [here](https://github.com/nrel/hopp#installing-from-source)

2. Clone this repo into the HOPP repo in the examples folder
   ```
   cd HOPP/examples
   git clone https://github.com/dguittet/HOPP-demos.git
   ```

### Running Configurations

There are multiple configurations in the results folder. To run the `EP3.75_GC_0_NPV` configuration,

```
python results/EP3.75_GC_0_NPV/README.json
```

Which will produce the `results.log.jsonl` output file in the same directory which has information on the optimization and best candidates.

### Exploring Results

The notebook `results/Plot_Outputs.ipynb` shows various plots of the inputs and results.
