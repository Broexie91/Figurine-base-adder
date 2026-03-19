FROM mambaorg/micromamba

# Set environment variables
ENV MICROMAMBA_ROOT=/opt/micromamba
ENV PATH=$MICROMAMBA_ROOT/bin:$PATH

# Create a new micromamba environment and install CadQuery dependencies
RUN micromamba create -n cadquery -c conda-forge cadquery --yes \
    && micromamba clean --all --yes \
    && micromamba activate cadquery