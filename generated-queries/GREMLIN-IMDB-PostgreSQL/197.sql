SELECT count(*)
FROM company_type, link_type, movie_companies, movie_info, movie_info_idx, movie_link, title
WHERE company_type.kind = 'special effects companies'
  AND movie_companies.company_type_id = company_type.id
  AND movie_companies.movie_id = title.id
  AND movie_info.movie_id = title.id
  AND movie_info_idx.movie_id = title.id
  AND movie_link.link_type_id = link_type.id
  AND movie_link.linked_movie_id = title.id;
