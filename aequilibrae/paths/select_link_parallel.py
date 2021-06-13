import multiprocessing as mp
from typing import List, Dict
import numpy as np

from aequilibrae.paths.assignment_paths import AssignmentPaths
from aequilibrae import logger

try:
    from aequilibrae.paths.AoN import select_link_for_origin
except ImportError as ie:
    logger.warning(f"Could not import procedures from the binary. {ie.args}")


class SelectLinkParallel(object):
    def __init__(self, table_name: str, demand_matrices: Dict) -> None:
        """
        Instantiates the class
         Args:
            table_name (str): Name of the traffic assignment result table used to generate the required path files
            demand_matrices (dict): Dict with assignment class id and corresponding demand matrix
        """
        self.paths = AssignmentPaths(table_name)
        self.num_iters = self.paths.assignment_results.get_number_of_iterations()
        self.classes = self.paths.assignment_results.get_traffic_class_names_and_id()
        self.demand_matrices = demand_matrices
        self.num_zones = list(self.demand_matrices.values())[0].matrix_view.shape[0]  # TODO: is this the way to go?

        # get weight of each iteration to weight corresponding demand.
        self.demand_weights = None
        # FIXME (Jan 21/4/21): this is MSA only atm, needs to be implemented for CFW and BFW
        self._calculate_demand_weights()

    def _calculate_demand_weights(self) -> None:
        """Each iteration of traffic assignment contributes a certain fraction to the total solutions. This method
        figures out how much so we can calculate select link matrices by weighting paths per iteration."""

        assignment_method = self.paths.assignment_results.get_assignment_method()

        if assignment_method == "msa":
            self.demand_weights = np.repeat(1.0 / self.num_iters, self.num_iters)
        else:
            raise ValueError(
                f"Asignment method {assignment_method} cannot be used for select link analysis at the moment."
            )
        sum_of_contribs = np.sum(self.demand_weights)
        assert np.allclose(sum_of_contribs, 1.0), f"Contribution of iterations is not one, but {sum_of_contribs}"

    def _initialise_matrices(self, num_links: int) -> Dict[str, np.array]:
        """ For each class initialise a select link demand matrix"""
        select_link_matrices = {
            c.__id__: np.zeros_like(self.demand_matrices[c.__id__].matrix_view) for c in self.classes
        }

        for c in self.classes:
            select_link_matrices[c.__id__] = np.repeat(
                select_link_matrices[c.__id__][:, :, np.newaxis], num_links, axis=2
            )

        return select_link_matrices

    def run_select_link_analysis(self, link_ids: List[int]) -> Dict[str, np.array]:
        """" Select link analysis for a provided set of links. Processing is done per iteration, class, and origin.
         Providing a list of links means we only need to read each path file once from disk. Note that link ids refer
         to the network ids, these are then turned into simplified ids; this means a bi-directional link will have two
         associated simplified link ids"""
        assert len(set(link_ids)) == len(link_ids), "Please provide a unique list of link ids"
        link_ids = np.array(link_ids)
        num_links = len(link_ids)
        select_link_matrices = self._initialise_matrices(num_links)

        for iteration in range(1, self.num_iters + 1):
            logger.info(f"Procesing iteration {iteration} for select link analysis")
            weight = self.demand_weights[iteration - 1]  # zero based
            for c in self.classes:
                class_id = c.__id__
                logger.info(f" Procesing class {class_id}")
                for origin in range(self.num_zones):
                    if origin % 100 == 0:
                        logger.info(f" Procesing origin {origin}")
                    # skip zero-demand origins
                    # TODO (Jan 13/6/21): this mess has to be cleaned up at some point, why do we have 2d matrices?
                    # if len(self.demand_matrices[class_id].matrix_view.shape) == 2:
                    if not np.nansum(self.demand_matrices[class_id].matrix_view[origin, :]):
                        continue
                    # elif not np.nansum(self.demand_matrices[class_id].matrix_view[origin, :, :]):
                    #     continue
                    sl_mat = select_link_matrices[class_id]
                    # FROM HERE
                    path_o_f, path_o_index_f = self.paths.get_path_file_names(origin, iteration, class_id)
                    select_link_for_origin(
                        link_ids,
                        num_links,
                        origin,
                        path_o_f,
                        path_o_index_f,
                        self.demand_matrices[class_id],
                        weight,
                        sl_mat,
                    )

                    # path_o, path_o_index = self.paths.read_path_file(origin, iteration, class_id)
                    # path_o = path_o.to_numpy().flatten()
                    # path_o_index = path_o_index.to_numpy().flatten()
                    # # # TODO JAN: why did I do this? was this from before I fixed the path file saving bug?
                    # # # drop disconnected zones (and intrazonal). Depends on index being ordered.
                    # # path_o_index_no_zeros = path_o_index.drop_duplicates(keep="first")
                    # dest_this_o_and_iter = np.array([np.argwhere(path_o_index > x).min() for x in np.argwhere(path_o == link_id).flatten()]).astype(int)
                    # select_link_matrices[class_id][origin, dest_this_o_and_iter] += (
                    #     weight
                    #     * self.demand_matrices[class_id].matrix_view[origin, dest_this_o_and_iter]
                    # )

        # logger.info(f"Select link analysis for links {link_id} finished.")
        return select_link_matrices