SET join_collapse_limit = 1;
SELECT count(*)
FROM ((company_type CROSS JOIN (movie_link CROSS JOIN link_type)) CROSS JOIN ((movie_companies CROSS JOIN movie_info_idx) CROSS JOIN title)) CROSS JOIN movie_info
WHERE company_type.kind = 'production companies'
  AND movie_companies.company_type_id = company_type.id
  AND movie_companies.movie_id = title.id
  AND movie_info.movie_id = title.id
  AND movie_info_idx.movie_id = title.id
  AND movie_link.link_type_id = link_type.id
  AND movie_link.linked_movie_id = title.id;
