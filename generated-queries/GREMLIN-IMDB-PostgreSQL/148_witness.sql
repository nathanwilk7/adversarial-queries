SET join_collapse_limit = 1;
SELECT count(*)
FROM (((((((((movie_companies CROSS JOIN (title CROSS JOIN movie_link)) CROSS JOIN movie_info) CROSS JOIN aka_title) CROSS JOIN cast_info) CROSS JOIN company_name) CROSS JOIN info_type) CROSS JOIN link_type) CROSS JOIN movie_keyword) CROSS JOIN person_info) CROSS JOIN role_type
WHERE aka_title.title = 'Anonima ricatti'
  AND aka_title.movie_id = title.id
  AND cast_info.movie_id = title.id
  AND cast_info.role_id = role_type.id
  AND movie_companies.company_id = company_name.id
  AND movie_companies.movie_id = title.id
  AND movie_info.info_type_id = info_type.id
  AND movie_info.movie_id = title.id
  AND movie_keyword.movie_id = title.id
  AND movie_link.link_type_id = link_type.id
  AND movie_link.linked_movie_id = title.id
  AND person_info.info_type_id = info_type.id;
