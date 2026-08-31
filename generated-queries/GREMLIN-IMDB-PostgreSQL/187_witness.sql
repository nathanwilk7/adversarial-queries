SET join_collapse_limit = 1;
SELECT count(*)
FROM (((((((movie_companies CROSS JOIN (title CROSS JOIN name)) CROSS JOIN movie_link) CROSS JOIN company_name) CROSS JOIN cast_info) CROSS JOIN movie_info_idx) CROSS JOIN link_type) CROSS JOIN info_type) CROSS JOIN role_type
WHERE name.name_pcode_nf = ''
  AND cast_info.movie_id = title.id
  AND cast_info.person_id = name.id
  AND cast_info.role_id = role_type.id
  AND movie_companies.company_id = company_name.id
  AND movie_companies.movie_id = title.id
  AND movie_info_idx.info_type_id = info_type.id
  AND movie_info_idx.movie_id = title.id
  AND movie_link.link_type_id = link_type.id
  AND movie_link.linked_movie_id = title.id;
